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

import os as _os
from config import (
    AGENT_NAME,
    AGENT_TIMEOUT,
    DOMAIN_FILTER,
    GITHUB_REPO,
    HOSTNAME,
    LOCAL_REPO_PATH,
    ORCHESTRATOR_URL,
    POLL_INTERVAL,
    PREFERRED_AGENT,
    WORKTREE_BASE,
)
# True when this runner was launched with an explicit PREFERRED_AGENT env var
# (i.e., a per-backend LaunchAgent plist). In that case the orchestrator's
# global "preferred" config must not override it.
_BACKEND_EXPLICITLY_SET = _os.getenv("PREFERRED_AGENT") is not None
import httpx as _httpx
from github_client import fetch_wo_markdown
from orchestrator_client import (
    checkin,
    claim,
    complete,
    get_agent_config,
    get_dispatch_status,
    get_next,
    get_prior_rejections,
    get_thread_messages,
    post_thread_message,
    release_dispatch,
    request_validate,
)
from prompt_builder import (
    build_prompt, format_prior_context, slug_from_title,
    update_memory_after_completion, update_memory_after_failure,
)
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


async def _analyze_failure(wo_id: str, context: str) -> str:
    """Call claude -p to produce a short root-cause diagnosis of a build/CI failure."""
    import subprocess as _sp
    prompt = (
        f"A CI or build step just failed for work order {wo_id}. "
        "Give a 3-5 sentence root-cause diagnosis and the exact file/line fix the agent must apply. "
        "Be specific and actionable — no preamble, no markdown headers.\n\n"
        f"{context}"
    )
    def _run() -> str:
        try:
            result = _sp.run(
                ["claude", "-p", prompt],
                capture_output=True, text=True, timeout=90,
            )
            return result.stdout.strip()
        except Exception as e:
            _log(f"{wo_id} _analyze_failure error: {e}")
            return ""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run)


async def _generate_validation_steps(wo_id: str, title: str, pr_url: str, worktree: str, wo_spec: dict) -> list[str]:
    """Ask Claude to write specific, human-readable verification steps for the validation banner."""
    import subprocess as _sp

    # Get changed files
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "main...HEAD", "--name-only", "--diff-filter=ACM",
            cwd=worktree,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        changed = out.decode(errors="replace").strip().splitlines()
    except Exception:
        changed = []

    ui_files = [f for f in changed if f.startswith("frontend/src/")]
    api_files = [f for f in changed if any(f.startswith(p) for p in (
        "src/clarion/api/routes/", "src/clarion/api/schemas/",
        "services/data-service/routes/", "services/gateway/routes/",
    ))]
    backend_files = [f for f in changed if f not in ui_files and f not in api_files]

    spec_context = "\n".join(filter(None, [
        f"Notes: {wo_spec.get('notes', '')}" if wo_spec.get("notes") else "",
        f"Services: {wo_spec.get('services', '')}" if wo_spec.get("services") else "",
    ]))

    file_lines = []
    if ui_files:   file_lines.append(f"UI ({len(ui_files)}): {', '.join(ui_files[:5])}")
    if api_files:  file_lines.append(f"API ({len(api_files)}): {', '.join(api_files[:4])}")
    if backend_files: file_lines.append(f"Backend ({len(backend_files)}): {', '.join(backend_files[:5])}")

    prompt = f"""Write a short verification checklist for a product owner reviewing this completed work order.
They are NOT a developer. Be specific, plain English, no code.

WO: {wo_id} — {title}
PR: {pr_url}
Files changed: {chr(10).join(file_lines) if file_lines else 'unknown'}
{spec_context}

Write 3-5 numbered steps. Each step must:
- Start from the Clarion app at https://localhost (login: admin / Clarion#Admin1)
- Name the EXACT page, menu, or element (e.g. "click Devices in the top nav > open any endpoint")
- State what SUCCESS looks like for that step

End with one line starting "Approve when: " summarising the pass condition.

If this is a backend/migration-only change with no visible UI impact, write:
"No visual verification needed — this is a backend-only change. The code review and CI gates confirmed correctness."
Then "Approve when: you have reviewed the PR diff and it matches the WO description."

Keep the total response under 300 words."""

    def _run() -> str:
        try:
            result = _sp.run(
                ["claude", "-p", prompt],
                capture_output=True, text=True, timeout=90,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, _run)

    if text and len(text) > 50:
        # Return as a list of lines for the steps field
        return [line for line in text.splitlines() if line.strip()]

    # Fallback
    steps = [f"Open PR #{pr_url.split('/')[-1]}: {pr_url}"]
    if ui_files:
        steps.append("Open https://localhost → log in as admin / Clarion#Admin1 and verify the UI changes look correct")
    steps.append("Confirm the implementation matches the WO specification")
    return steps


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
            # Worktree exists from a previous agent run. Reset uncommitted changes so
            # this agent starts clean — stale edits from a failed/interrupted agent
            # must not bleed into a new agent's implementation.
            # We keep commits (agent 1 may have pushed real work) but wipe dirty state.
            _log(f"Worktree exists — resetting uncommitted state before re-entry: {worktree_dir}")
            for cmd in (
                ["git", "checkout", "."],           # revert tracked modifications
                ["git", "clean", "-fd"],             # remove untracked files (not .gitignore'd — node_modules safe)
            ):
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=worktree_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
            _log(f"Worktree clean — resuming at {worktree_dir}")
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
    """Return a plain-text summary of files committed on this branch vs main."""
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "main...HEAD", "--name-status",
        cwd=worktree,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    lines = out.decode(errors="replace").strip().splitlines()
    if not lines:
        return "No committed changes vs main."
    new_files = [l.split("\t", 1)[1] for l in lines if l.startswith("A")]
    modified  = [l.split("\t", 1)[1] for l in lines if l.startswith(("M", "R"))]
    parts = []
    if new_files:
        names = ", ".join(new_files[:8]) + (" ..." if len(new_files) > 8 else "")
        parts.append(f"New ({len(new_files)}): {names}")
    if modified:
        names = ", ".join(modified[:8]) + (" ..." if len(modified) > 8 else "")
        parts.append(f"Modified ({len(modified)}): {names}")
    return " | ".join(parts) if parts else "No changes."


async def _commit_and_push(wo_id: str, slug: str, worktree: str, title: str, monitor) -> str:
    """Commit WO changes, push the branch, open a PR, and return the PR URL.

    Returns the GitHub PR URL on success, or "" if there was nothing to commit.
    Auto-generated help docs (frontend/public/help/) are discarded before
    staging so they never appear in WO commits.
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

    # Discard auto-generated help docs before checking status — the doc-writer
    # agent leaves these modified in every worktree but they're never WO work.
    await _git("checkout", "--", "frontend/public/help/")

    # Check for any remaining changes (staged, unstaged, or untracked)
    rc, status = await _git("status", "--porcelain")
    if not status:
        _log(f"{wo_id} worktree is clean after stripping noise — nothing to commit")
        return ""

    # Stage everything that remains
    await _git("add", "-A")

    # Commit
    commit_msg = f"feat({wo_id.lower()}): {title[:72]}\n\nImplemented by {AGENT_NAME} via agentic factory."
    rc, out = await _git("commit", "-m", commit_msg)
    if rc != 0:
        _log(f"{wo_id} git commit failed: {out[:200]}")
        await monitor.post(f"⚠️ Git commit failed:\n```\n{out[:400]}\n```")
        return ""

    _log(f"{wo_id} committed: {out.splitlines()[0] if out else '(no output)'}")

    # Push — pass venv-enriched PATH so the pre-push hook finds black/ruff
    rc, out = await _git("push", "-u", "origin", branch, env=push_env)
    if rc != 0:
        _log(f"{wo_id} git push failed: {out[:200]}")
        await monitor.post(f"⚠️ Git push failed:\n```\n{out[:400]}\n```\nBranch: `{branch}`")
        return ""

    _log(f"{wo_id} pushed branch {branch}")

    # Open PR
    pr_proc = await asyncio.create_subprocess_exec(
        "gh", "pr", "create",
        "--title", f"{wo_id}: {title[:60]}",
        "--body", f"## Summary\n\nImplemented by {AGENT_NAME} (backend: {PREFERRED_AGENT}) via agentic factory.\n\n🤖 Submitted for human review before merge.",
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
        return pr_url
    else:
        _log(f"{wo_id} gh pr create failed: {pr_url[:200]}")
        await monitor.post(f"✅ Changes pushed to `{branch}` — PR creation failed, will submit validate without pr_url")
        return ""


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

    # Inject prior failure context so the agent knows exactly what to fix on retry
    prior_rejections = await get_prior_rejections(wo_id)
    thread_msgs = await get_thread_messages(wo_id) if prior_rejections else []
    prior_ctx = format_prior_context(prior_rejections, thread_msgs)
    if prior_ctx:
        _log(f"{wo_id} retry #{len(prior_rejections)}: injecting prior rejection context")

    prompt = build_prompt(wo_spec, wo_markdown, worktree_path, AGENT_NAME, prior_context=prior_ctx)
    backend = get_backend(preferred_agent)

    attempt_label = f"retry #{len(prior_rejections)}" if prior_rejections else "first attempt"
    _log(f"Starting {preferred_agent} backend for {wo_id} ({attempt_label})")
    await checkin(wo_id, f"starting agent ({attempt_label})")
    await post_thread_message(wo_id, f"Starting implementation of **{wo_id}**: {title} ({attempt_label})")

    monitor = ThreadMonitor(wo_id)

    # Fallback order: only include backends that are actually installed.
    # Claude excluded — use PREFERRED_AGENT=claude explicitly if needed.
    from draft_server import _probe_backends as _probe
    _available = _probe()
    _FALLBACK_ORDER = [b for b in ["cursor", "codex", "gemini"] if _available.get(b)]

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
            build_analysis = await _analyze_failure(
                wo_id,
                f"Docker container build failed for {wo_id}.\n\nBuild output:\n{rebuild['output'][-3000:]}"
            )
            if build_analysis:
                await post_thread_message(wo_id, f"🔍 **Build failure analysis:**\n\n{build_analysis}", msg_type="ci_analysis")
            await release_dispatch(wo_id)
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
            failures.append("CI tests failed")
        if not gate["security_passed"]:
            count = gate.get("finding_count", 0)
            failures.append(f"{count} CRITICAL/HIGH security issue{'s' if count != 1 else ''} found")
        failure_str = ", ".join(failures)
        _log(f"{wo_id} quality gate FAILED: {failure_str} — not submitting for validation")
        await checkin(wo_id, f"quality gate failed: {failure_str}")

        # Extract only the most meaningful error lines — don't dump 1000 chars of raw output
        raw_output = gate.get("ci_output", "")
        error_lines = [
            l.rstrip() for l in raw_output.splitlines()
            if l.strip() and any(w in l.lower() for w in
               ("error", "failed", "assert", "exception", "traceback", "import", "syntax"))
        ]
        error_excerpt = "\n".join(error_lines[:8]) if error_lines else raw_output[-400:].strip()

        await post_thread_message(
            wo_id,
            f"❌ **Quality gate failed — the agent will fix this automatically**\n\n"
            f"**What failed:** {failure_str}\n\n"
            + (f"**Key errors:**\n```\n{error_excerpt}\n```\n\n" if not gate["ci_passed"] and error_excerpt else "")
            + "Analyzing root cause...",
            msg_type="ci_result",
            metadata={"ci_passed": gate["ci_passed"], "security_passed": gate["security_passed"],
                      "findings": gate["bandit_findings"][:5]},
        )
        failure_detail = raw_output if not gate["ci_passed"] else str(gate.get("bandit_findings", ""))
        ci_analysis = await _analyze_failure(
            wo_id,
            f"CI/security gate failed for {wo_id}.\n\nFailure: {failure_str}\n\nOutput:\n{failure_detail[-3000:]}"
        )
        if ci_analysis:
            await post_thread_message(
                wo_id,
                f"🔍 **Root cause & fix:**\n\n{ci_analysis}",
                msg_type="ci_analysis"
            )
        update_memory_after_failure(wo_id, failure_str, services=wo_spec.get("services", ""))
        await release_dispatch(wo_id)
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

    # Commit, push, and open the PR BEFORE requesting validation so the
    # human reviews real committed code and so pr_url can be included in
    # the validate payload (the orchestrator now requires it).
    await checkin(wo_id, "committing and opening PR for review")
    pr_url = await _commit_and_push(wo_id, slug, worktree_path, title, monitor)
    if not pr_url:
        _log(f"{wo_id} nothing committed or PR creation failed — aborting")
        await monitor.post("⚠️ Nothing to commit after removing noise, or PR creation failed. Manual intervention needed.")
        return

    # Request human validation with the PR URL attached
    validation_steps = await _generate_validation_steps(wo_id, title, pr_url, worktree_path, wo_spec)
    thread_summary = title
    validated = await request_validate(
        wo_id,
        verify_url=pr_url,
        steps=validation_steps,
        ci_passed=gate["ci_passed"],
        security_passed=gate["security_passed"],
        thread_summary=thread_summary,
        pr_url=pr_url,
    )
    if not validated:
        _log(f"{wo_id} validate rejected by orchestrator — check error in thread")
        await monitor.post("⚠️ Orchestrator rejected the validation request — see thread for details.")
        return

    # Wait for human decision
    _log(f"{wo_id} awaiting human approval...")
    await monitor.post("PR open and submitted for review. Monitoring thread for questions while waiting...")
    decision = await _poll_approval(wo_id, monitor=monitor)
    if decision == "approved":
        _log(f"{wo_id} approved — marking complete")
        await checkin(wo_id, "approved: marking complete")
        await complete(wo_id)
        _log(f"{wo_id} complete")
        update_memory_after_completion(wo_id, wo_spec)
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

    # Fetch agent config from orchestrator — Settings UI changes take effect without restart.
    # If this runner was started with an explicit PREFERRED_AGENT (per-backend LaunchAgent),
    # the orchestrator's global preferred setting must not override it.
    agent_cfg = await get_agent_config()
    if _BACKEND_EXPLICITLY_SET:
        active_backend = PREFERRED_AGENT
    else:
        active_backend = agent_cfg.get("preferred", PREFERRED_AGENT) if agent_cfg else PREFERRED_AGENT
        if active_backend != PREFERRED_AGENT:
            _log(f"Orchestrator config sets backend: {PREFERRED_AGENT} → {active_backend}")

    while True:
        # Check for a PM-dispatched WO — use its backend override if present
        dispatched = draft_server.pop_dispatch()
        next_wo = await get_next(domain=DOMAIN_FILTER)
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
