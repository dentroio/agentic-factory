# Bring your own repo

The factory engine already takes a GitHub repo via `GITHUB_REPO` (or dashboard **Settings**). That repo can be public or private. It does **not** need to be any particular private product.

You do **not** need to clone or access any other application. You need a GitHub repo the factory token can read (and write, if you want agents to open PRs).

## Checklist

1. Create or pick a GitHub repository (the [template](https://github.com/dentroio/agentic-factory-template) is the fastest path; this page is for an **existing** codebase).
2. Add folders the engine looks for:
   - `docs/project_management/work_orders/` (or set `WO_SPECS_DIR`)
   - `docs/factory/runs/`
3. Optional: `docs/factory/PLAN.json` if you use the dispatch queue.
4. Copy [PROCESS.md](PROCESS.md) to `AGENT_PROCESS.md` at the repo root (or point your agent front doors at `docs/adopters/PROCESS.md` if you vendor this kit).
5. Add labels: `new-wo`, `agent-pr`, `pm-sync`.
6. Protect `main` with your own CI required check.
7. Optionally paste workflows from [`templates/github/`](../../templates/github/) into **that** repo’s `.github/workflows/` — not into this engine’s existing workflows.
8. Point the factory at it:
   - First-time CLI: `make agent-setup` (this repo) and set the repo to `owner/your-app`
   - Or dashboard Settings → the GitHub repo field
9. Write one sample WO, claim it, implement against **your** verify command.

## What you must not do

- Do not change this engine’s running services or live `.github/workflows/` to “support” your app.
- Do not put private product secrets in a public fork of the factory.
- Do not assume Docker, a specific language, or a specific verify command. Those belong in **your** repo.
