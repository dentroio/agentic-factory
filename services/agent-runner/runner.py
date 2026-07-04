"""Agent runner — polls the orchestrator, claims WOs, and runs the configured agent backend."""
import asyncio
import sys
from pathlib import Path

from backends import get_backend
from config import (
    AGENT_NAME,
    AGENT_TIMEOUT,
    GITHUB_REPO,
    HOSTNAME,
    POLL_INTERVAL,
    PREFERRED_AGENT,
    WORKTREE_BASE,
)
from github_client import fetch_wo_markdown
from orchestrator_client import (
    checkin,
    claim,
    complete,
    get_dispatch_status,
    get_next,
    post_thread_message,
    request_validate,
)
from prompt_builder import build_prompt, slug_from_title
from quality_gate import run_quality_gate
from thread_monitor import ThreadMonitor, _is_question


def _log(msg: str) -> None:
    print(f"[runner] {msg}", flush=True)


async def _checkin_loop(wo_id: str, interval: int = 90) -> None:
    """Background task: send heartbeats every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        await checkin(wo_id, "working")


async def _handle_qa(wo_id: str, question: str, monitor: ThreadMonitor, backend) -> None:
    """Answer a human question without blocking the main agent task."""
    if backend is None:
        await monitor.post(f"**Q: {question}**\n\nNo agent backend available to answer right now.")
        return
    answer = await backend.ask(
        f"While working on {wo_id}, the human asked: {question}\n\n"
        f"Answer briefly in the context of this work order. Be concise (2-4 sentences)."
    )
    if answer:
        await monitor.post(f"**Q: {question}**\n\n{answer}")


async def _thread_monitor_loop(wo_id: str, monitor: ThreadMonitor, backend) -> None:
    """Background task: poll thread every 15s for human messages while agent works."""
    await asyncio.sleep(30)  # give agent time to start before first poll
    while True:
        await asyncio.sleep(15)
        messages = await monitor.poll()
        for msg in messages:
            content = msg.get("content", "").strip()
            if not content:
                continue
            _log(f"[{wo_id}] thread message from human: {content[:80]}")
            if _is_question(content):
                asyncio.create_task(_handle_qa(wo_id, content, monitor, backend))
            else:
                await backend.inject(content)
                await monitor.post(f"Guidance received — incorporated: _{content[:120]}_")


async def _poll_approval(
    wo_id: str, monitor: "ThreadMonitor | None" = None, timeout: int = AGENT_TIMEOUT
) -> str:
    """Poll dispatch state until approved, rejected, or timeout.
    Handles thread Q&A from humans while waiting.
    """
    waited = 0
    while waited < timeout:
        await asyncio.sleep(15)
        waited += 15
        status = await get_dispatch_status(wo_id)
        if status in ("awaiting_commit", "approved"):
            return "approved"
        if status == "rejected":
            return "rejected"
        if monitor:
            messages = await monitor.poll()
            for msg in messages:
                content = msg.get("content", "").strip()
                if content and _is_question(content):
                    asyncio.create_task(_handle_qa(wo_id, content, monitor, None))
    return "timeout"


async def run_wo(wo_spec: dict) -> None:
    wo_number = wo_spec.get("wo", wo_spec.get("number", "?"))
    wo_id = f"WO-{wo_number}" if not str(wo_number).startswith("WO-") else str(wo_number)
    title = wo_spec.get("title", "Unknown")
    slug = slug_from_title(title, wo_number)

    _log(f"Claiming {wo_id}: {title}")
    if not await claim(wo_id, slug):
        _log(f"{wo_id} already claimed — skipping")
        return

    worktree_path = str(Path(WORKTREE_BASE) / f"wo-{slug}")

    # Fetch the full WO markdown for the prompt
    wo_markdown = await fetch_wo_markdown(
        int(str(wo_number).replace("WO-", "")),
        wo_path="docs/project_management/work_orders",
    )

    prompt = build_prompt(wo_spec, wo_markdown, worktree_path, AGENT_NAME)
    backend = get_backend(PREFERRED_AGENT)

    _log(f"Starting {PREFERRED_AGENT} backend for {wo_id}")
    await checkin(wo_id, "starting agent")
    await post_thread_message(wo_id, f"Starting implementation of **{wo_id}**: {title}")

    monitor = ThreadMonitor(wo_id)

    # Run the agent with a timeout; thread monitor runs in parallel
    checkin_task = asyncio.create_task(_checkin_loop(wo_id))
    monitor_task = asyncio.create_task(_thread_monitor_loop(wo_id, monitor, backend))
    try:
        async with asyncio.timeout(AGENT_TIMEOUT):
            async for chunk in backend.run(prompt, worktree_path):
                if chunk.strip():
                    _log(f"[{wo_id}] {chunk[:120]}")
                    await checkin(wo_id, chunk[:80])
    except TimeoutError:
        _log(f"{wo_id} timed out after {AGENT_TIMEOUT}s")
    finally:
        checkin_task.cancel()
        monitor_task.cancel()

    _log(f"{wo_id} agent run complete — running quality gate")
    await checkin(wo_id, "quality gate: running CI + security scan")
    await post_thread_message(wo_id, "Agent run complete. Running quality gate (CI + security scan)...")

    gate = await run_quality_gate(worktree_path)
    _log(f"{wo_id} gate: ci={'✅' if gate['ci_passed'] else '❌'} "
         f"security={'✅' if gate['security_passed'] else '❌'} "
         f"findings={gate['finding_count']}")

    if not gate["ci_passed"] or not gate["security_passed"]:
        failures = []
        if not gate["ci_passed"]:
            failures.append("CI failed")
        if not gate["security_passed"]:
            failures.append(f"{gate['finding_count']} CRITICAL/HIGH security findings")
        failure_str = ", ".join(failures)
        _log(f"{wo_id} quality gate FAILED: {failure_str} — not submitting for validation")
        await checkin(wo_id, f"quality gate failed: {failure_str}")
        await post_thread_message(
            wo_id,
            f"❌ Quality gate failed: {failure_str}\n\n"
            + (f"CI output:\n```\n{gate['ci_output'][-1000:]}\n```" if not gate["ci_passed"] else ""),
            msg_type="ci_result",
            metadata={"ci_passed": gate["ci_passed"], "security_passed": gate["security_passed"],
                      "findings": gate["bandit_findings"][:5]},
        )
        return

    await post_thread_message(
        wo_id,
        "✅ Quality gate passed — CI and security checks clear. Requesting human review.",
        msg_type="ci_result",
        metadata={"ci_passed": True, "security_passed": True},
    )

    # Request human validation (gate passed)
    validated = await request_validate(
        wo_id,
        verify_url=f"http://localhost:8099/wo/{str(wo_number).replace('WO-', '')}",
        steps=["Review the implementation", "Check outputs match WO spec"],
        ci_passed=gate["ci_passed"],
        security_passed=gate["security_passed"],
        thread_summary=f"Implemented {wo_id}: {title}",
    )
    if not validated:
        _log(f"{wo_id} validate rejected — agent must fix and retry (manual intervention needed)")
        return

    # Wait for human decision — also poll thread for questions during wait
    _log(f"{wo_id} awaiting human approval...")
    await monitor.post("Implementation submitted for review. Monitoring thread for questions while waiting...")
    decision = await _poll_approval(wo_id, monitor=monitor)
    if decision == "approved":
        _log(f"{wo_id} approved — agent should commit and push (handled in agent subprocess)")
        await complete(wo_id)
        _log(f"{wo_id} complete")
    elif decision == "rejected":
        _log(f"{wo_id} rejected — check the factory dashboard for guidance")
    else:
        _log(f"{wo_id} approval timed out — leaving in awaiting_human state")


async def main() -> None:
    _log(f"Agent runner starting — backend={PREFERRED_AGENT}, agent={AGENT_NAME}@{HOSTNAME}")
    _log(f"Polling orchestrator every {POLL_INTERVAL}s")

    while True:
        next_wo = await get_next()
        if next_wo and next_wo.get("wo"):
            await run_wo(next_wo)
        else:
            _log("No WO available — sleeping")
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log("Shutting down")
        sys.exit(0)
