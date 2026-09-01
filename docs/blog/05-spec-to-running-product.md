# Part 5 — From spec to a running product

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

---

The spec is on `main`. The planning agent has gone home. An implementer — Claude Code or Cursor on the Mac, Docker humming — is about to do the only job Layer A is for.

This post is the path. If you skip a step, you will still get a pull request. You will not get a product.

## 1. Sync and isolate

```bash
make sync
make wo-start NNN=001 SLUG=import-page-redesign
cd .worktrees/wo-001-import-page-redesign
```

`make sync` pulls the branch you are on and, if `main` moved, rebuilds containers that changed. Starting a WO on last week’s laptop is how you rebase-conflict with work you did not know shipped.

`make wo-start` creates a git **worktree** at `.worktrees/wo-NNN-slug/` on a new branch `wo/NNN-slug` cut from `origin/main`. `.worktrees/` is gitignored. Each implementer gets a full checkout. Checking out a different branch *inside* an existing worktree is forbidden. That is how directory names and branches silently diverge, and how you rebuild the wrong tree.

The script refuses if the branch already exists locally or on origin — another agent claimed it. It may symlink `.env` so local secrets still work. It may share `node_modules` from the main checkout so `make ci-local` can typecheck without a two-minute install that would kill a factory runner’s timeout.

**All agents share one Docker Compose stack** when the product uses Docker. Isolation is git, not runtime. Two agents rebuilding the same shared service at the same time overwrite each other’s deployed image. That is Part 7’s “one agent per shared service,” not a Compose bug.

## 2. Claim the WO before any product code

The first commit on the branch is not a feature. It is a flag on the factory board:

```json
{
  "wo": 1,
  "title": "the import UI: page redesign + candidate data-quality fixes",
  "agent": "cursor",
  "agent_platform": "cursor-ide",
  "status": "in_progress",
  "step": "starting",
  "started_at": "2026-08-22T14:00:00Z",
  "last_updated": "2026-08-22T14:00:00Z",
  "branch": "wo/001-import-page-redesign",
  "notes": ""
}
```

Push it. Until you do, the Status Site cannot say who is working. `make wt-clean` cannot know the worktree is later safe to delete. A second agent scanning `git branch -r` might still race you if you delay the push.

`step` advances: `starting` → `implementing` → `writing-tests` → `fixing-ci` → `waiting-for-review` → `done`. Stuck? `status: blocked` and a `notes` string a human can read. Schema: see the adopter [CLAIM_SCHEMA.md](../adopters/CLAIM_SCHEMA.md).

Remote Codex on GitHub Actions still needs a claim. If the workflow skips it, the board lies and cleanup tooling goes blind.

## 3. Implement, then bake the image

Follow the spec. After **every** change that should be visible in the running product:

```bash
your verify/rebuild command SVC=<service>
make wait-healthy
make smoke-test
```

| Files changed | Rebuild |
|---------------|---------|
| Shared library or API service | that service |
| A file copied into two images | **both** images |
| Frontend | production frontend build |

`CACHE_BUST` on rebuild so Docker cannot serve yesterday’s Python from a cached layer.

This is the step people skip, and the step that makes the product's factory different from “agent opens a PR against a Node app.” If you do not rebuild, you are verifying a hallucination of the old container.

Vite (or any hot-reload dev server) is preview. The production image is what we ship. Committing on the preview alone is a class of bug with a name: **stale frontend**.

Dangerous substitutes:

| Dangerous | Safe | Failure |
|-----------|------|---------|
| `your rebuild command` from a worktree | `your verify/rebuild command` | Builds main; WO changes never enter the image |
| `compose up --force-recreate <svc>` | worktree-aware rebuild (`--no-deps`) | Recreates supporting infra; wipes env |
| `docker start` after re-tag | `up -d --no-build --force-recreate --no-deps` | Starts a stale image |

If the service dies on boot: `make logs-svc SVC=…` → fix → rebuild → `wait-healthy`. “The unit tests passed on the host” is not “the container imported the module.”

## 4. Stop. Ask a human.

After smoke tests pass, the implementer **does not commit**.

For UI:

> Deployed. Open the running app in a browser. Expected: full-width tab, Protocol column, no discovery-protocol noise. Confirm and I’ll commit.

For backend-only:

> Curl from the running container: `…`. Does this look right? Should I commit?

If the human reports a problem: fix → rebuild → ask again. Same rule after a CI fix that changes behavior. The agent does not get to decide that a follow-up lint commit is “invisible.”

P3 docs skip this step. There is no running behavior to check.

This checkpoint is easy to resent. It is the reason the factory does not ship “looks good in the model’s head.” the product's interesting bugs are empty states, wrong joins, and UI that typechecks but lies. Those are visible to a person in the product. They are not visible to `pytest` alone. They are not visible to Factory Codex in GitHub Actions. That is why UI WOs run locally.

Oryntra (Part 4) can make this conversation spatial — a circle on the tab instead of a paragraph. It does not replace the checkpoint. It sharpens it.

## 5. The local gate

```bash
make ci-local
```

On the Mac, this is the PR Gate:

1. Lint
2. Unit tests
3. Schema / migration registration (if you have it)
4. Auth coverage on new routes (if you have it)
5. Frontend typecheck, tests, production build (if you have them)
6. Local static checks — the product scars, no API bill

Those static checks are the cheap twin of the GitHub AI reviewer: hardcoded secrets, SQL f-strings, bare `except:`, `|| true`, missing commits after writes, unregistered migrations, new routes without auth, TypeScript `any`. Fix these before the first push or you will pay for a review → fix → re-review loop, and you will wake the auto-fixer.

Passing `ci-local` before `gh pr create` is how you keep Layer B specialists from fighting the implementer.

## 6. PM docs in the same commit as the code

Before the PR:

- Spec: `**Status:** ✅ Complete (YYYY-MM-DD)`
- Claim: `"status": "complete"` and `completed_at` — **this PR**. You cannot stamp it after merge.
- `PROGRESS.md` row
- `CAPABILITY_STATUS.md` if a capability changed
- wiki / canonical docs per `docs_impact`

Then stage **explicit paths**. Never `git add -A`. Scope is direction (Part 2). Drive-by formatting of an unrelated file is how two WOs collide in review.

```bash
git add path/to/changed/file
git commit -m "feat(ui): the redesign WO — import tab and candidate quality"
git push
```

## What “done” means here

Done is not “the agent wrote files.” Done is:

1. The spec’s acceptance criteria are true **in the running containers**
2. A human said so
3. `make ci-local` is green
4. The claim and the spec will tell the truth after merge

GitHub is the next room, not a substitute for this room. Remote agents stop at step 5 and write After Merge rebuild commands in the PR body. If they skip that, the next `make sync` on the Mac is how you discover the feature never existed in Docker.

**Next:** [Part 6 — GitHub, CI, and who is allowed to merge](06-github-ci-and-the-gate.md)
