---
name: claude-cli-subprocess-must-strip-anthropic-api-key
description: Every subprocess call to the `claude` CLI in agent-runner must use backends.claude._subscription_env() and explicitly pass --model, or it will silently bill via metered API instead of the subscription.
metadata:
  type: project
---

Any `claude` CLI subprocess invocation in services/agent-runner that doesn't pass `env=_subscription_env()` inherits the parent process's ambient `ANTHROPIC_API_KEY` (set for review_chain.py's direct API calls) and silently switches from subscription login to metered billing. This happened twice: PR #62 fixed only backends/claude.py's two call sites, missing four more in runner.py (`_analyze_failure`, verification-guide helper) and reviewer.py (`_claude_review`, `generate_verification_guide`) — credits kept draining after the "fix" landed because those sites weren't audited.

**Why:** There is no compiler/linter check tying `claude` subprocess calls to env stripping — it's a convention, not an enforced invariant, so it's easy to add a new call site and forget it.

**How to apply:** Before merging any PR that adds/touches a `subprocess.run(["claude", ...])` or `asyncio.create_subprocess_exec(claude_bin, ...)` call, grep the whole agent-runner service for all `claude` CLI invocations and confirm each one passes `env=_subscription_env()` (imported from `backends.claude`) and an explicit `--model