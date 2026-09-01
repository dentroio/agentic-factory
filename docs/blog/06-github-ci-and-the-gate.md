# Part 6 — GitHub, CI, and who is allowed to merge

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

---

The implementer has a green `make ci-local` and a human who clicked the tab. Now the work leaves the laptop.

GitHub is not “where we host the code.” It is where Layer B lives: the PR Gate, the reviewer, the fixer, the applier, the merge advisor, the branch updater, the watchdog. If Part 4 was the cast list, this post is the scene they share.

## Branch names are a protocol

| Prefix | Meaning |
|--------|---------|
| `wo/NNN-slug` | Implementation of work order NNN |
| `fix/short-description` | Hotfix — no WO spec (see the end) |
| `docs/short-description` | P3 documentation |

`wo/NNN-*` is the claim visible in `git branch -r`. Auto-update-PRs, the Status Site, and “is someone already on this?” all key off that prefix. `feature/steve-wip` is invisible to the factory. It will rot, collide, and never get `main` merged in.

`main` is protected. The required status check is **PR Gate**. Direct pushes are rejected, including P3. Docs still ride a PR. That is slower than the old “P3 goes straight to main” idea and it is why `PROGRESS.md` cannot be quietly backfilled after merge.

## Opening the PR

```bash
gh pr create --title "feat(services): the redesign WO — discovery tab and candidate quality" --body "..."
```

The body is a template, not a novel: Summary, link to the Work Order, migrations checklist, test plan, **After Merge** rebuild commands (for any machine that pulls), UI verification steps copied from the human checkpoint.

P2 only, **after reading the AI review comment**:

```bash
gh pr merge --auto --squash
make pr-watch
```

P0/P1: do not set auto-merge. Print the URL. A human still owns the button.

## The PR Gate (what actually blocks)

`.github/workflows/ci.yml` — every PR to `main`, every push to `main`. Parallel jobs on self-hosted Linux. About nine minutes. No `|| true` on the gate.

| Job | Proves |
|-----|--------|
| Runner pre-clean | Disk on the self-hosted runner |
| Gitleaks | No secrets in **this PR’s** commits (`base..HEAD`, not every branch the clone can see) |
| Lint | Black + Ruff |
| Unit tests | `pytest tests/unit/` + coverage upload |
| Frontend | `tsc`, Jest, production `npm run build` |
| Migration safety | Every migration is registered in the runner your project uses |
| RBAC coverage | Prefix rules cannot gate only some HTTP methods |
| **PR Gate** | Aggregator. This is the required GitHub check. |

Gitleaks used to scan so wide that a secret on an unrelated unmerged branch failed every other open PR. The factory encodes its scars. Scope the scanner to the PR.

Heavy work is **not** on the PR path: integration tests on push to `main`, weekly security / container / DAST scans, wiki build, synthetic clustering validation. Keep the per-PR gate cheap. Put expensive proof on a calendar.

## The comment loop (advisory AI, mechanical blockers)

**AI reviewer** posts LGTM / Needs attention / Review required. Advisory as a required check (exit 0). Binding as a *norm* for agents.

**Applier** may commit `[ai-review-apply]` on Needs attention, once.

**CI auto-fix** may commit `[ci-autofix]` on red CI, twice.

**Merge advisor** then posts Ready / Review / Do not merge with a checklist. Never blocks. Exists so a human on a P1 does not have to reconstruct the plot from six check runs.

Implementer rules:

- Review required → fix the code; do not auto-merge
- Needs attention → fix if real; if false positive, say so on the PR, then auto-merge
- LGTM → P2 may auto-merge
- Never auto-merge on CI green alone — the review workflow is separate and may not have posted yet

## pr-watch owns the rest of the night

`make pr-watch` (`scripts/pr_watch.sh`) is the implementer’s babysitter after the PR exists. Default timeout two hours.

| Event | Action |
|-------|--------|
| Lint failure | `make format` → `[pr-watch-fix]` → push (max 2) |
| Branch out of date | Merge `main` → push |
| Cloud commits (applier / auto-fix) | Pull, **rebuild local containers** so localhost still matches the PR |
| CI code failure | Exit — fix, rebuild, **ask the human again**, push |
| Review required | Exit 1 |
| P2 + green + auto-merge | Wait until MERGED, pull `main`, rebuild |
| P1 + green | Print URL; poll until a human merges or closes |
| MERGED | Rebuild changed images, delete remote branch, remove worktree, delete local branch |
| CLOSED without merge | Fail |

This is the difference between “agent opened a PR and wandered off” and “the WO landed on `main` and local Docker matches it.”

When cloud commits appear, rebuilding locally is not polish. The applier might have changed Python. If you do not bake, the human’s next click is against a lie.

## Auto-update: `main` does not wait for you

Every push to `main`, `auto-update-prs.yml` merges `main` into open `wo/*` branches. P0/P1 never get auto-merge, so without this they silently drift until GitHub says “out of date” at the worst moment.

`PROGRESS.md` conflicts take main — main is authoritative; the branch row will be in the squash. Other conflicts are the implementer’s problem. A PAT push re-triggers CI. `GITHUB_TOKEN` pushes do not, which is how auto-merge stalls until a human clicks “Approve to run.” The PAT has expired quietly for weeks. The workflow now falls back and warns rather than dying at checkout. Factory specialists fail in boring ways. Design for that.

## After merge, tell the truth

`mark-wo-done-on-merge.yml` stamps the board from the PR title. It must ignore its own bookkeeping PRs (`pm-sync`) or it will rewrite history to point at itself. The implementer should already have marked the claim complete **in the feature PR**. The workflow is backstop, not plan.

`pr-watch` on MERGED: pull, `rebuild_changed.sh`, worktree gone. `make sync` on any other laptop: same rebuild. If the WO was GitHub Codex, this is the first time Docker sees the code. Read the After Merge section. Actually run it.

## Merge authority, one more time

```
P0 / P1  →  human reads the PR, maybe clicks localhost, merges
P2       →  human already verified localhost before commit;
            CI green + AI review LGTM → auto squash-merge
P3       →  PR still required; no Docker; no user checkpoint
```

Auto-merge is not production unsupervised. It is “the irreversible product check already happened on a Mac.”

## Hotfix track (when there is no WO)

```
Is this planned work from a WO?  YES → WO track
                                 NO  → Hotfix track
```

1. `git fetch` and check `origin/fix/*` so two agents do not duplicate the incident.
2. `git checkout -b fix/short-description` and push immediately (the claim).
3. Investigate **on that branch**.
4. Fix, `ci-local`, PR with Problem / Fix / Verification, `pr-watch`.

Risk tier still applies. A hotfix that touches auth is still P0. A hotfix that should have been a WO gets a spec filed *after* so the next agent is not hunting Slack.

## Watchdog

Planning agent, Dependabot bridge, auto-update-PRs: if they fail N times running, one tracking issue. Close it when they succeed. Unattended automation that nobody watches is how a factory looks busy and does nothing.

---

GitHub is a building full of specialists. They still cannot click the running UI. That is why Part 5 exists. The next post is what happens when *several* implementers share one repo — and when the *product’s* agents start to look like the same idea.

**Next:** [Part 7 — Many agents, one repo](07-many-agents-one-repo.md)
