# WO-1053 — Antares Security Reviewer Backend

**Created:** 2026-08-08
**Priority:** P1
**Effort:** M
**Services:** agent-runner, orchestrator, status-site
**Repos:** `dentroio/agentic-factory`
**Depends on:** —
**Status:** ✅ Complete

---

## Background

The factory already enforces a security gate with deterministic scanners:
Bandit for Python, Semgrep for rule-based static analysis, and a lightweight
JS/TS security scan. It also runs an LLM peer review chain where the security
reviewer is currently assigned to the same pool of general coding/review
backends as the other review roles.

The user wants the factory to support Cisco Foundation AI's Antares models as a
local or network-hosted security reviewer. Antares is purpose-built for
vulnerability localization, so it is a good complement to Bandit/Semgrep rather
than a replacement. The factory should let users run Antares on this Mac or on
another LAN device, choose a model profile based on available hardware, test the
endpoint from the UI, and decide whether Antares findings are advisory or
blocking.

Because this affects security-review behavior and validation gates, implement
conservatively: Antares is advisory by default, produces structured findings,
and can be promoted to blocking only through explicit configuration.

## What to Build

Add `antares` as a first-class security reviewer backend for the factory.

### Backend Client

Create an Antares client in the agent runner that can call an OpenAI-compatible
local endpoint:

```text
POST {ANTARES_BASE_URL}/v1/chat/completions
```

Support these settings:

```text
ANTARES_ENABLED=false
ANTARES_BASE_URL=http://localhost:8000
ANTARES_MODEL=fdtn-ai/antares-350m | fdtn-ai/antares-1b | custom
ANTARES_API_KEY=
ANTARES_TIMEOUT_SECONDS=120
ANTARES_MODE=advisory | blocking
ANTARES_BLOCKING_SEVERITIES=CRITICAL,HIGH
```

The backend must:

- Send only the WO context, changed-file diff, and relevant prior scanner
  findings.
- Ask Antares for security-only output.
- Require structured JSON findings with severity, file, line, issue, and fix.
- Treat malformed model output as a non-blocking scan error in advisory mode.
- Treat timeout, connection failure, or malformed output as blocking only when
  Antares is configured as required/blocking.
- Never send source code to a cloud endpoint unless the user explicitly
  configures `ANTARES_BASE_URL` that way.

### Model Profiles

Add model-profile support:

| Profile | Model value | Intended use |
|---------|-------------|--------------|
| Auto recommended | `auto` | Factory recommends a profile from local hardware or remote `/models` response |
| Antares 350M | `fdtn-ai/antares-350m` | Lower-memory Macs, M1 8GB, CPU-only/shared machines |
| Antares 1B | `fdtn-ai/antares-1b` | M1/M2/M3 16GB+, higher-quality local review |
| Custom | user supplied | GGUF paths, future Antares releases, remote GPU hosts |

For local mode, recommend:

```text
Apple M1 + <= 8GB RAM  -> Antares 350M
Apple M1 + >= 16GB RAM -> Antares 1B
Unknown hardware       -> Antares 350M
```

For network mode, do not guess remote specs. Probe the remote Antares service
for available models and health data if it exposes either:

```text
GET {ANTARES_BASE_URL}/health
GET {ANTARES_BASE_URL}/v1/models
```

If the remote service does not expose model metadata, show the configured model
and a warning that the factory cannot verify remote hardware suitability.

### Factory UI

Add an Antares section to Settings → Agents / Reviewer Assignments.

UI fields:

- Enable Antares security reviewer.
- Run location: `This machine` or `Another device on network`.
- Endpoint URL.
- Model profile: Auto recommended, Antares 350M, Antares 1B, Custom.
- Custom model value/path.
- Mode: Advisory or Blocking on configured severities.
- Blocking severities multi-select or checkboxes for CRITICAL/HIGH/MEDIUM/LOW.
- Test Antares Connection button.

The UI should display:

- Endpoint reachability.
- Available models when the server exposes them.
- Current recommended model and why.
- Whether Antares is advisory or blocking.

Manual reviewer assignment should include `Antares` as a selectable backend for
the Security reviewer only. It must not be available for architecture,
correctness, performance, or documentation reviewers unless a future WO expands
the backend beyond security.

### Review Chain Integration

Integrate Antares into `services/agent-runner/review_chain.py`.

Behavior:

- When the Security reviewer is assigned to `antares`, call the Antares backend
  instead of Claude/Codex/Cursor/Gemini.
- Format Antares findings using the existing review thread format.
- Preserve the existing blocking-severity contract:
  CRITICAL/HIGH block when configured blocking; otherwise they are posted as
  advisory findings.
- Include prior Bandit/Semgrep/JS findings in the Antares prompt so the model
  can reason about them, deduplicate, or localize related vulnerable files.

### Quality Gate Integration

Add an optional Antares scan step to `services/agent-runner/quality_gate.py`.

Behavior:

- Runs in parallel with CI, Bandit, Semgrep, and JS security scan when enabled.
- Scans only changed files/diff, not the full repository by default.
- Returns `antares_findings`, `antares_error`, and `antares_passed`.
- Adds Antares findings to the existing `finding_count`.
- Does not block in advisory mode.
- Blocks `security_passed` only in blocking mode when configured severities are
  present or when Antares is required and unavailable.

### Operator Documentation

Document two supported serving shapes:

```text
Factory Mac -> localhost Antares server
Factory Mac -> LAN Antares server on another device
```

Include examples for:

- Apple M1 local lightweight profile.
- Network endpoint profile.
- Advisory mode.
- Blocking mode.

Do not require the WO to ship a production Antares model server. The factory
only needs a clean endpoint contract and UI/client integration. A follow-up WO
can add a one-command local server installer if needed.

## Requirements

```yaml
requires:
  connectors: []
  services:
    - agent-runner
    - orchestrator
    - factory-status
```

## Domain Notes

- Conflict-magnet files:
  - `services/agent-runner/review_chain.py`
  - `services/agent-runner/quality_gate.py`
  - `services/orchestrator/orchestrator.py`
  - `services/status-site/templates/settings_agents.html`
- Copy existing reviewer config patterns from the current reviewer assignment
  UI and `/api/config` flow.
- Do not make Antares the default blocking gate on first rollout.
- Do not remove or weaken Bandit, Semgrep, JS scan, or the existing peer review
  chain.
- Do not allow arbitrary unauthenticated LAN access by default when the factory
  itself exposes any proxy or test endpoint. Store secrets through the existing
  authentication/settings pattern.
- Treat model output as untrusted. Parse and validate it before using it in
  thread messages or gate decisions.
- The Antares backend is security-only in this WO.

## Acceptance Criteria

- [ ] Settings UI exposes Antares configuration with enable toggle, endpoint,
      run location, model profile, custom model value, advisory/blocking mode,
      and blocking severities.
- [ ] UI recommends Antares 350M vs 1B for local Apple Silicon based on
      available memory, and explains when remote hardware cannot be inferred.
- [ ] `Test Antares Connection` verifies reachability and model availability
      without running a full review.
- [ ] Security reviewer assignment supports `Antares`; non-security reviewer
      roles do not offer Antares.
- [ ] `review_chain.py` can run the security reviewer through Antares and post
      structured findings to the WO thread.
- [ ] `quality_gate.py` optionally runs Antares alongside existing scanners and
      includes Antares findings/errors in its structured result.
- [ ] Advisory mode never blocks validation solely because Antares found issues
      or failed to respond; findings are still visible in the WO thread.
- [ ] Blocking mode fails `security_passed` on configured severities and fails
      closed when Antares is required but unreachable.
- [ ] Existing Bandit, Semgrep, JS security scan, and Claude/Codex/Cursor/Gemini
      reviewer behavior remains unchanged when Antares is disabled.
- [ ] Unit tests cover: disabled Antares, successful LGTM response, structured
      findings response, malformed output, timeout/unreachable endpoint,
      advisory vs blocking mode, model-profile recommendation, and role
      filtering in reviewer assignments.
- [ ] `make ci-local` passes.

## Verification Steps

```bash
# Unit and static checks
make ci-local

# Optional local mock server verification
python3 -m pytest tests/unit/ -k "antares" -v

# Manual browser verification after rebuilding services
make restart
open http://localhost:8099/settings/agents

# Expected UI checks:
# 1. Antares settings section is visible.
# 2. Security reviewer can be set to Antares.
# 3. Architecture/correctness/performance/documentation reviewers cannot be set to Antares.
# 4. Test Antares Connection reports success against a mock/OpenAI-compatible endpoint.
# 5. Advisory mode shows findings without blocking.
# 6. Blocking mode marks security_passed=false for HIGH/CRITICAL findings.
```

## Execution

> This section is read by agents before starting implementation.

**Branch:** `wo/1053-antares-security-reviewer-backend`
**Risk tier:** P1 — security review/gate behavior, human approval and merge
required.
**PR title:** `feat(security): WO-1053 — Antares Security Reviewer Backend`
**Auto-merge:** no
**Pre-PR gate:** `make ci-local`

**PM docs to update after merge:**

- `docs/project_management/PROGRESS.md` — add/mark WO-1053 complete.
- `docs/project_management/CAPABILITY_STATUS.md` — add Antares security
  reviewer capability under Agent Runner and/or CI/CD + Agent Infrastructure.

**Files to touch (estimated):**

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/agent-runner/backends/antares.py` | Antares/OpenAI-compatible client and security-only prompt handling |
| Modify | `services/agent-runner/backends/__init__.py` | Register/probe `antares` backend |
| Modify | `services/agent-runner/review_chain.py` | Route security reviewer to Antares and format findings |
| Modify | `services/agent-runner/quality_gate.py` | Optional Antares scan result and gate integration |
| Modify | `services/orchestrator/orchestrator.py` | Persist Antares settings and expose connection test endpoint if needed |
| Modify | `services/status-site/main.py` | Read/write Antares settings, proxy connection test if needed |
| Modify | `services/status-site/templates/settings_agents.html` | Add Antares UI controls and security-only reviewer option |
| Modify | `services/agent-runner/prompt_builder.py` | Mention Antares behavior in quality gate instructions if needed |
| Create/Modify | `tests/unit/test_antares_backend.py` | Antares backend parsing, timeout, advisory/blocking tests |
| Create/Modify | `tests/unit/test_antares_config.py` | Settings/model recommendation/role filtering tests |
| Modify | `docs/wiki/Agent-Backends.md` | Document Antares reviewer backend |
| Modify | `docs/wiki/Getting-Started.md` | Add optional local/LAN Antares setup notes |

**Key constraints:**

- Antares must be disabled by default.
- Advisory mode must be the default when enabled.
- Blocking mode must be explicit.
- Antares failures must be visible; they must not look identical to a clean
  scan.
- Existing security gates must remain active.
- Do not ship a bundled model or require a model download during `make ci-local`.

### UI Verification

1. Open `http://localhost:8099/settings/agents`.
2. Enable Antares security reviewer.
3. Select `This machine`, `Auto recommended`, and `Advisory`.
4. Expected: the UI shows a recommendation for 350M or 1B based on local
   hardware, with a short reason.
5. Change run location to `Another device on network` and enter an endpoint.
6. Click `Test Antares Connection`.
7. Expected: reachability/model status is shown, or a clear error appears if
   the endpoint is unavailable.
8. Confirm only the Security reviewer dropdown can select `Antares`.
9. Confirm no errors in browser DevTools console.

## Notes / Context

- Antares should be treated as an additional local security signal beside
  Bandit and Semgrep, not as a replacement.
- Antares model profiles should support official Hugging Face model IDs and
  custom model names/paths because users may serve GGUF conversions through
  llama.cpp or another OpenAI-compatible runtime.
- Follow-up candidate: add a one-command local Antares server helper for Apple
  Silicon using `llama.cpp` or another runtime once the backend contract is
  stable.
