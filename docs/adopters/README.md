# Adopter kit (generic process — no product required)

**Status:** Additive documentation. Does not change factory services or existing workflows.

This folder is the **public, product-agnostic** copy of the Work Order process: how to specify work, claim it, and merge it. Point the factory engine at **any** GitHub repo. You do not need access to any private application.

| Doc | What it is |
|-----|------------|
| [PROCESS.md](PROCESS.md) | Risk tiers, claim files, human checkpoint, never-dos |
| [CONTRACT.md](CONTRACT.md) | Branch names, labels, paths the dashboard already understands |
| [WO_SPEC_FORMAT.md](WO_SPEC_FORMAT.md) | Spec template + synthetic examples |
| [CLAIM_SCHEMA.md](CLAIM_SCHEMA.md) | `docs/factory/runs/WO-NNN.json` |
| [BYO.md](BYO.md) | Point `GITHUB_REPO` at an existing repo |
| [../blog/README.md](../blog/README.md) | Essay series on why this process exists |

Paste-able GitHub workflow copies (do **not** replace this repo’s live `.github/workflows/`): [`../../templates/github/`](../../templates/github/).

A clone-and-go demo lives in the separate template repo: [dentroio/agentic-factory-template](https://github.com/dentroio/agentic-factory-template).
