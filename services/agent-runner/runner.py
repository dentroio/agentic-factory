"""Agent runner — polls the orchestrator, claims WOs, and runs the configured agent backend."""
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import usage_tracker
from backends import get_backend
from backends.base import BackendHangError, QuotaExceededError
from backends.cursor import CursorConnectionError
import backends.quota_state as quota_state

_BACKEND_FAIL = (CursorConnectionError, BackendHangError)
import re

from config import (
    AGENT_NAME,
    AGENT_TIMEOUT,
    GITHUB_REPO,
    HOSTNAME,
    LOCAL_REPO_PATH,
    ORCHESTRATOR_URL,
    POLL_INTERVAL,
    PREFERRED_AGENT,
    WORKTREE_BASE,
)
import httpx as _httpx
from github_client import fetch_wo_markdown
from orchestrator_client import (
    checkin,
    claim,
    complete,
    get_agent_config,
    get_dispatch_status,
    get_next,
    post_thread_message,
    request_validate,
)
from prompt_builder import build_prompt, slug_from_title
from quality_gate import run_container_rebuild, run_quality_gate, _ci_env
from review_chain import get_worktree_diff, run_review_chain
from thread_monitor import ThreadMonitor, _is_question


def _log(msg: str) -> None:
    line = f"[runner] {msg}"
    print(line, flush=True)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_post_log(line))
    except RuntimeError:
        pass  # not in async context — print only


async def _post_log(line: str) -> None:
    try:
        async with _httpx.AsyncClient(timeout=1.0) as c:
            await c.post(f"{ORCHESTRATOR_URL}/api/log", json={"line": line, "agent": AGENT_NAME})
    except Exception:
        pass


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


async def _setup_worktree(wo_number: str | int, title: str) -> str:
    """Create and return the worktree path for this WO.

    If LOCAL_REPO_PATH is configured, runs wo_start.sh inside the local clone
    so the agent gets a fully-initialised git worktree with the right branch.
    Otherwise falls back to a plain directory under WORKTREE_BASE.
    """
    num = re.sub(r"^WO-0*", "", str(wo_number)) or str(wo_number)
    title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].rstrip("-")

    if LOCAL_REPO_PATH:
        worktree_dir = str(Path(LOCAL_REPO_PATH) / ".worktrees" / f"wo-{num}-{title_slug}")
        if Path(worktree_dir).exists():
            _log(f"Worktree already exists at {worktree_dir} — resuming")
            return worktree_dir
        _log(f"Creating worktree via wo_start.sh: wo-{num}-{title_slug}")
        proc = await asyncio.create_subprocess_exec(
            "bash", "scripts/wo_start.sh", num, title_slug,
            cwd=LOCAL_REPO_PATH,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"wo_start.sh failed:\n{out.decode(errors='replace')[:600]}")
        _log(f"Worktree ready: {worktree_dir}")
        return worktree_dir

    # Fallback: plain directory (Docker / non-git mode)
    worktree_dir = str(Path(WORKTREE_BASE) / f"wo-{num}-{title_slug}")
    Path(worktree_dir).mkdir(parents=True, exist_ok=True)
    return worktree_dir


async def _build_change_summary(worktree: str) -> str:
    """Return a plain-text summary of files the agent created or modified."""
    proc = await asyncio.create_subprocess_exec(
        "git", "status", "--short",
        cwd=worktree,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    lines = out.decode(errors="replace").strip().splitlines()
    if not lines:
        return "No file changes detected."
    new_files = [l[3:] for l in lines if l.startswith("??")]
    modified = [l[3:] for l in lines if not l.startswith("??")]
    parts = []
    if new_files:
        names = ", ".join(new_files[:8]) + (" ..." if len(new_files) > 8 else "")
        parts.append(f"New ({len(new_files)}): {names}")
    if modified:
        names = ", ".join(modified[:8]) + (" ..." if len(modified) > 8 else "")
        parts.append(f"Modified ({len(modified)}): {names}")
    return " | ".join(parts) if parts else "No changes."


async def _commit_and_push(wo_id: str, slug: str, worktree: str, title: str, monitor) -> bool:
    """Commit all changes in the worktree, push the branch, and open a PR.

    Returns True if a commit was created, False if the tree was already clean.
    Runs shell commands directly — no AI backend needed for this step.
    """
    num = re.sub(r"[^0-9]", "", wo_id)
    branch = f"wo/{num}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40].rstrip('-')}"

    push_env = _ci_env(worktree)

    async def _git(*args, env=None) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=worktree,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        out, _ = await proc.communicate()
        return proc.returncode, out.decode(errors="replace").strip()

    # Check for any changes (staged, unstaged, or untracked)
    rc, status = await _git("status", "--porcelain")
    if not status:
        _log(f"{wo_id} worktree is clean — nothing to commit")
        return False

    # Stage everything
    await _git("add", "-A")

    # Commit
    commit_msg = f"feat({wo_id.lower()}): {title[:72]}\n\nImplemented by {AGENT_NAME} via agentic factory."
    rc, out = await _git("commit", "-m", commit_msg)
    if rc != 0:
        _log(f"{wo_id} git commit failed: {out[:200]}")
        await monitor.post(f"⚠️ Git commit failed:\n```\n{out[:400]}\n```")
        return False

    _log(f"{wo_id} committed: {out.splitlines()[0] if out else '(no output)'}")

    # Push — pass venv-enriched PATH so the pre-push hook finds black/ruff
    rc, out = await _git("push", "-u", "origin", branch, env=push_env)
    if rc != 0:
        _log(f"{wo_id} git push failed: {out[:200]}")
        await monitor.post(f"⚠️ Git push failed:\n```\n{out[:400]}\n```\nBranch: `{branch}`")
        return True  # commit was created, just push failed

    _log(f"{wo_id} pushed branch {branch}")

    # Open PR
    pr_proc = await asyncio.create_subprocess_exec(
        "gh", "pr", "create",
        "--title", f"{wo_id}: {title[:60]}",
        "--body", f"## Summary\n\nImplemented by {AGENT_NAME} (backend: {PREFERRED_AGENT}) via agentic factory.\n\n🤖 Auto-committed after human approval.",
        "--base", "main",
        "--head", branch,
        cwd=worktree,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    pr_out, _ = await pr_proc.communicate()
    pr_url = pr_out.decode(errors="replace").strip()
    if pr_proc.returncode == 0:
        _log(f"{wo_id} PR created: {pr_url}")
        await monitor.post(f"✅ Committed, pushed, and PR opened: {pr_url}")
    else:
        _log(f"{wo_id} gh pr create failed: {pr_url[:200]}")
        await monitor.post(f"✅ Changes pushed to `{branch}` — open PR manually:\n```\ngh pr create --head {branch}\n```")

    return True


async def run_wo(wo_spec: dict, preferred_agent: str = PREFERRED_AGENT) -> None:
    wo_number = wo_spec.get("wo", wo_spec.get("number", "?"))
    wo_id = f"WO-{wo_number}" if not str(wo_number).startswith("WO-") else str(wo_number)
    title = wo_spec.get("title", "Unknown")
    slug = slug_from_title(title, wo_number)
    start_time = datetime.now(UTC)
    ask_calls: list[dict] = []

    _log(f"Claiming {wo_id}: {title}")
    if not await claim(wo_id, slug, backend=preferred_agent):
        _log(f"{wo_id} already claimed — skipping")
        return

    worktree_path = await _setup_worktree(wo_number, title)

    # Fetch the full WO markdown for the prompt
    wo_markdown = await fetch_wo_markdown(
        int(str(wo_number).replace("WO-", "")),
        wo_path="docs/project_management/work_orders",
    )

    prompt = build_prompt(wo_spec, wo_markdown, worktree_path, AGENT_NAME)
    backend = get_backend(preferred_agent)

    _log(f"Starting {preferred_agent} backend for {wo_id}")
    await checkin(wo_id, "starting agent")
    await post_thread_message(wo_id, f"Starting implementation of **{wo_id}**: {title}")

    monitor = ThreadMonitor(wo_id)

    # Fallback order: only include backends that are actually installed.
    # Claude is last — it consumes subscription quota.
    from draft_server import _probe_backends as _probe
    _available = _probe()
    _FALLBACK_ORDER = [b for b in ["cursor", "codex", "gemini", "claude"] if _available.get(b)]

    async def _run_one(b, name):
        async with asyncio.timeout(AGENT_TIMEOUT):
            async for chunk in b.run(prompt, worktree_path):
                if chunk.strip():
                    _log(f"[{wo_id}] {chunk[:120]}")
                    await checkin(wo_id, chunk[:80])

    async def _run_with_fallback(active_backend, active_name):
        checkin_task = asyncio.create_task(_checkin_loop(wo_id))
        monitor_task = asyncio.create_task(_thread_monitor_loop(wo_id, monitor, active_backend))
        try:
            try:
                await _run_one(active_backend, active_name)
            except QuotaExceededError as exc:
                quota_state.mark_exhausted(active_name)
                _log(f"{wo_id} ⚠️ {active_name} quota exhausted — marking and trying fallbacks")
                await checkin(wo_id, f"{active_name} quota exhausted")
                await post_thread_message(wo_id, f"⚠️ **{active_name}** hit its usage limit — trying fallback backends")
                raise  # handled below alongside _BACKEND_FAIL
            except _BACKEND_FAIL as exc:
                _log(f"{wo_id} {exc} — trying fallback backends")
                await post_thread_message(wo_id, f"⚠️ {exc}")
                raise
        except (QuotaExceededError, *_BACKEND_FAIL):
            for fallback_name in _FALLBACK_ORDER:
                if fallback_name == active_name:
                    continue
                if quota_state.is_exhausted(fallback_name):
                    _log(f"{wo_id} skipping {fallback_name} — quota exhausted this session")
                    continue
                try:
                    fallback = get_backend(fallback_name)
                    _log(f"{wo_id} retrying with {fallback_name} backend")
                    await checkin(wo_id, f"retrying with {fallback_name}")
                    await post_thread_message(wo_id, f"Retrying with **{fallback_name}** backend...")
                    await _run_one(fallback, fallback_name)
                    return  # fallback succeeded
                except QuotaExceededError:
                    quota_state.mark_exhausted(fallback_name)
                    _log(f"{wo_id} {fallback_name} quota exhausted — skipping")
                    continue
                except (*_BACKEND_FAIL, RuntimeError) as e:
                    _log(f"{wo_id} {fallback_name} also failed: {e}")
                    continue
            _log(f"{wo_id} all backends failed or exhausted")
        except TimeoutError:
            _log(f"{wo_id} timed out after {AGENT_TIMEOUT}s")
        finally:
            checkin_task.cancel()
            monitor_task.cancel()

    await _run_with_fallback(backend, preferred_agent)

    _log(f"{wo_id} agent run complete — rebuilding changed containers")
    await checkin(wo_id, "rebuilding changed containers")
    await post_thread_message(wo_id, "Agent run complete. Detecting changed services and rebuilding containers...")

    rebuild = await run_container_rebuild(worktree_path)
    _log(f"{wo_id} rebuild: services={rebuild['services']} rebuilt={rebuild['rebuilt']} smoke={rebuild['smoke_passed']}")

    if rebuild["services"]:
        rebuild_status = "✅ rebuilt" if rebuild["rebuilt"] else "❌ build failed"
        smoke_status = "✅ smoke passed" if rebuild["smoke_passed"] else "⚠️ smoke failed"
        await post_thread_message(
            wo_id,
            f"Container rebuild: {', '.join(rebuild['services'])} — {rebuild_status}, {smoke_status}\n"
            f"```\n{rebuild['output'][-800:]}\n```",
        )
        if not rebuild["rebuilt"]:
            await checkin(wo_id, "container build failed — stopping")
            return
    else:
        await post_thread_message(wo_id, "No container changes detected (docs/scripts only) — skipping rebuild.")

    _log(f"{wo_id} running quality gate")
    await checkin(wo_id, "quality gate: running CI + security scan")
    await post_thread_message(wo_id, "Running quality gate (CI + security scan)...")

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
        "✅ Quality gate passed — CI and security checks clear. Running peer review chain...",
        msg_type="ci_result",
        metadata={"ci_passed": True, "security_passed": True},
    )

    # Run multi-agent peer review chain
    await checkin(wo_id, "peer review chain: running")
    diff = await get_worktree_diff(worktree_path)
    security_findings = [
        {"severity": "HIGH", "file": "bandit", "line": 0,
         "issue": f["issue_text"], "fix": ""}
        for f in gate.get("bandit_findings", [])
    ]

    # Fetch docs_required from the orchestrator queue DB
    docs_required: list[dict] = []
    try:
        import json as _json
        async with _httpx.AsyncClient(timeout=5) as _qc:
            _qr = await _qc.get(f"{ORCHESTRATOR_URL}/api/queue/{wo_id}")
            if _qr.status_code == 200:
                _entry = _qr.json()
                raw = _entry.get("docs_required", "[]")
                docs_required = _json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pass

    review_passed, all_findings = await run_review_chain(
        wo_spec, diff, monitor, security_findings,
        coding_backend=preferred_agent, docs_required=docs_required or None,
    )

    # Collect ask_calls from review chain findings
    ask_calls = [
        {"reviewer": f.get("reviewer", "unknown"), "backend": f.get("backend", "unknown")}
        for f in all_findings if "reviewer" in f
    ]

    if not review_passed:
        blocking = [
            f for f in all_findings
            if f.get("severity") in ("CRITICAL", "HIGH")
        ]
        _log(f"{wo_id} review chain FAILED — {len(blocking)} blocking issues — injecting into agent")
        await checkin(wo_id, f"review chain failed: {len(blocking)} blocking issues")
        await backend.inject(
            f"Peer review chain found {len(blocking)} blocking issue(s) that must be fixed:\n\n"
            + "\n".join(
                f"- [{f.get('severity')}] {f.get('file', '?')}:{f.get('line', '?')}: "
                f"{f.get('issue', '?')}"
                + (f"\n  Fix: {f['fix']}" if f.get("fix") else "")
                for f in blocking
            )
            + "\n\nFix all blocking issues and re-run CI. The review chain will run again."
        )
        return

    reviewer_count = len(set(f.get("reviewer") for f in all_findings if "reviewer" in f) or {"peers"})
    await monitor.post(
        f"✅ All reviewers signed off — peer review chain complete. Requesting human validation.",
        msg_type="text",
    )

    # Request human validation (gate + review chain both passed)
    change_summary = await _build_change_summary(worktree_path)
    thread_summary = f"{title} — {change_summary}"
    validated = await request_validate(
        wo_id,
        verify_url=f"http://localhost:8099/wo/{str(wo_number).replace('WO-', '')}",
        steps=[
            "Open 'View thread →' above for full agent notes",
            "Review the files listed above",
            "Confirm output matches the WO spec",
        ],
        ci_passed=gate["ci_passed"],
        security_passed=gate["security_passed"],
        thread_summary=thread_summary,
    )
    if not validated:
        _log(f"{wo_id} validate rejected — agent must fix and retry (manual intervention needed)")
        return

    # Wait for human decision — also poll thread for questions during wait
    _log(f"{wo_id} awaiting human approval...")
    await monitor.post("Implementation submitted for review. Monitoring thread for questions while waiting...")
    decision = await _poll_approval(wo_id, monitor=monitor)
    if decision == "approved":
        _log(f"{wo_id} approved — committing and pushing")
        await checkin(wo_id, "approved: committing and pushing")
        committed = await _commit_and_push(wo_id, slug, worktree_path, title, monitor)
        await complete(wo_id)
        _log(f"{wo_id} complete")
        if not committed:
            await monitor.post("⚠️ Nothing to commit — work may have already been pushed, or the agent made no file changes.")
        await usage_tracker.record_run(ORCHESTRATOR_URL, wo_id, preferred_agent, start_time, True, ask_calls)
    elif decision == "rejected":
        _log(f"{wo_id} rejected — check the factory dashboard for guidance")
        await usage_tracker.record_run(ORCHESTRATOR_URL, wo_id, preferred_agent, start_time, False, ask_calls)
    else:
        _log(f"{wo_id} approval timed out — leaving in awaiting_human state")
        await usage_tracker.record_run(ORCHESTRATOR_URL, wo_id, preferred_agent, start_time, False, ask_calls)


async def main(once: bool = False) -> None:
    _log(f"Agent runner starting — backend={PREFERRED_AGENT}, agent={AGENT_NAME}@{HOSTNAME}"
         + (" [--once]" if once else ""))
    _log(f"Polling orchestrator every {POLL_INTERVAL}s")

    # Fetch agent config from orchestrator — Settings UI changes take effect without restart
    agent_cfg = await get_agent_config()
    active_backend = agent_cfg.get("preferred", PREFERRED_AGENT) if agent_cfg else PREFERRED_AGENT
    if active_backend != PREFERRED_AGENT:
        _log(f"Orchestrator config overrides PREFERRED_AGENT: {PREFERRED_AGENT} → {active_backend}")
    else:
        active_backend = PREFERRED_AGENT

    while True:
        # Check for a PM-dispatched WO — use its backend override if present
        dispatched = draft_server.pop_dispatch()
        next_wo = await get_next()
        if next_wo and next_wo.get("wo"):
            backend_override = (
                next_wo.pop("_dispatch_backend", None)   # from /api/next when PM-dispatched
                or (dispatched or {}).get("backend")
            )
            run_backend = backend_override or active_backend
            if backend_override and backend_override != active_backend:
                _log(f"PM dispatch override: backend={run_backend}")
            await run_wo(next_wo, preferred_agent=run_backend)
            if once:
                _log("--once: WO complete, exiting")
                break
        else:
            _log("No WO available — sleeping")
            if once:
                _log("--once: nothing to claim, exiting")
                break
        # Interruptible sleep — PM dispatch via /dispatch endpoint wakes immediately
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: draft_server._wake_event.wait(timeout=POLL_INTERVAL)
        )
        draft_server._wake_event.clear()


if __name__ == "__main__":
    import threading
    import draft_server
    threading.Thread(target=draft_server.start, daemon=True, name="draft-server").start()
    once = "--once" in sys.argv
    try:
        asyncio.run(main(once=once))
    except KeyboardInterrupt:
        _log("Shutting down")
        sys.exit(0)
