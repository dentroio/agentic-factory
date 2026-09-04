# Bring your own repo

Use this when you already have an application and want the factory engine to drive Work Orders against it. For a greenfield demo, prefer the [product template](https://github.com/dentroio/agentic-factory-template) instead.

The engine already takes any GitHub repo via `GITHUB_REPO`. It does **not** need a particular private product.

## Checklist

### 0. Scaffold (recommended)

**Preferred — dashboard:** Settings → Get Started (GitHub, product checkout, agent/LLM). Then `make doctor`.

**CLI fallback** from your **engine** checkout:

```bash
make init PRODUCT=/absolute/path/to/your-app INIT_ARGS='--sample-wo'
make doctor DOCTOR_ARGS="--product /absolute/path/to/your-app --skip-network"
```

That writes `factory.yaml`, `AGENT_PROCESS.md` (from [PROCESS.md](PROCESS.md)), WO/claim folders, and an optional docs-only WO-001. Then finish the GitHub steps below.

### 1. Folders and process

If you skipped `make init`, create these by hand:

- [ ] `docs/project_management/work_orders/` — WO markdown (or set `WO_SPECS_DIR`)
- [ ] `docs/factory/runs/` — claim JSON (gitkeep is fine)
- [ ] Copy [PROCESS.md](PROCESS.md) to `AGENT_PROCESS.md` at the product root (edit URLs / verify commands to match your app)
- [ ] Optional: `docs/factory/PLAN.json` for the dispatch queue

### 2. Product profile

- [ ] Add root [`factory.yaml`](../wiki/Product-Profile.md) with at least:

```yaml
name: my-app
verify: "make ci-local"    # or pytest / npm test / your gate
ui_url: "http://localhost:YOUR_PORT"
ui_verify_hint: "Open the app; confirm the WO change. No passwords in this file."
compose_project: ""        # set only if agents rebuild shared Compose services
patterns_file: "docs/factory/patterns.md"
```

- [ ] Add `docs/factory/patterns.md` with the invariants agents must copy (auth, migrations, lockfiles, etc.)

### 3. GitHub

- [ ] Labels: `new-wo`, `agent-pr`, `pm-sync`
- [ ] Protect `main` with **your** CI as a required check
- [ ] Fine-grained PAT on the engine machine covering this product repo (+ the engine repo)
- [ ] Optional: paste workflows from [`templates/github/`](../../templates/github/) into **this** product only

### 4. Point the engine

- [ ] Engine: `make up` + `make agent-install`
- [ ] **Settings → Get Started** — PAT, repo, local path/clone, agent/LLM
- [ ] `make doctor` — all hard checks green
- [ ] Dashboard lists your WOs; run one sample WO end-to-end

(CLI alternative: `make agent-setup` + prefs — not required when using Get Started.)

## What “done” means for BYO

Agents run **your** `verify:` command in **your** worktree, open PRs on **your** GitHub, and ask humans to open **your** `ui_url`. If any of those still mention another product, the profile or prefs are wrong.

## What you must not do

- Do not replace the engine’s live `.github/workflows/` with product templates  
- Do not put product passwords in `factory.yaml`, prompts, or public forks of the engine  
- Do not assume the engine’s Makefile targets (`make deploy-changed`, etc.) exist in your app — put those in `factory.yaml` / your own Makefile  

## Related

- [Product Profile](../wiki/Product-Profile.md)  
- [CONTRACT.md](CONTRACT.md)  
- [Getting Started](../wiki/Getting-Started.md)  
- [WO_SPEC_FORMAT.md](WO_SPEC_FORMAT.md)  
