# Adopter kit — product-agnostic process

**Status:** Public documentation for anyone pointing the factory engine at their own GitHub repo.

This folder is the **product-side** process: how to specify work, claim it, and merge it. The engine already supports any `GITHUB_REPO`. You do not need access to any private third-party application.

| Doc | What it is |
|-----|------------|
| [PROCESS.md](PROCESS.md) | Risk tiers, claim files, human checkpoint, never-dos — copy to product `AGENT_PROCESS.md` |
| [CONTRACT.md](CONTRACT.md) | Paths, branches, labels, secrets the engine already understands |
| [WO_SPEC_FORMAT.md](WO_SPEC_FORMAT.md) | Spec template + examples |
| [CLAIM_SCHEMA.md](CLAIM_SCHEMA.md) | `docs/factory/runs/WO-NNN.json` |
| [BYO.md](BYO.md) | Checklist for an existing codebase |
| [../wiki/Product-Profile.md](../wiki/Product-Profile.md) | `factory.yaml` — verify, UI URL, patterns |

## Start here

1. Wiki: [Adopting](../wiki/Adopting.md) → [Getting Started](../wiki/Getting-Started.md)  
2. Product: [agentic-factory-template](https://github.com/dentroio/agentic-factory-template) **or** [BYO.md](BYO.md)  
3. Optional paste-in Actions (into the **product** only): [`../../templates/github/`](../../templates/github/)

## Historical note

[INDEPENDENCE.md](INDEPENDENCE.md) recorded the engineering program that removed hardcoded product coupling from the public engine. That work is **complete**. New adopters should follow Getting Started and Product Profile, not that checklist.
