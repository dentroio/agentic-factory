---
title: "Reliability & Monitoring"
description: "How the factory catches its own automation silently breaking, and how to check whether an AI reviewer is actually pulling its weight"
last_verified: 2026-07-30
covers_wos: []
doc_owner: factory-team
---

# Reliability & Monitoring

Built 2026-07-30 after a single audit found: the Doc Writer Agent had failed 30 of 30 scheduled runs, and the Dependabot→WO bridge's downstream trigger (`planning-agent.yml`) had never fired once, ever — both completely invisible from the dashboard the whole time. A green checkmark and a red one look identical for anything nobody's actively watching. This page covers the three pieces built in response.

## Automation Watchdog

`.github/workflows/automation-watchdog.yml` (present in this repo and in the product repo it builds, e.g. Clarion) listens for `workflow_run` completion on the unattended automations — `doc-writer.yml`, `planning-agent.yml`, `dependabot-wo-bridge.yml`, `api-canary.yml`. On a workflow's **2nd consecutive failure** (not the 1st, to skip single flaky runs), it files a GitHub issue tagged `automation-failure`; further failures comment on that same issue instead of creating duplicates. The issue closes itself automatically the next time the workflow succeeds.

Uses only the default `GITHUB_TOKEN` — no secrets to configure. Deliberately built on `workflow_run`, not the `issues: types: [labeled]` trigger that caused the original planning-agent failure, so a repeat of that exact bug class can't also silently take out the thing meant to alert on it.

**To monitor another workflow:** add its exact `name:` field to the `workflows:` list in `automation-watchdog.yml`.

**If you see a `🔴 ... has failed N times in a row` issue:** check the linked run's logs. Nothing else needs configuring — the issue itself has everything you need to start debugging.

## API Canary

`.github/workflows/api-canary.yml` runs `scripts/api_canary.py` once daily: a minimal real call to the Anthropic API (trivial prompt, `max_tokens=16`) using the same model-resolution and response-parsing logic every other script here shares. Costs a fraction of a cent per run.

This exists because unit tests mock the API and structurally cannot catch a real response-shape mismatch — which is exactly what broke on 2026-07-30: switching the default model to `claude-sonnet-5` broke `message.content[0].text` everywhere (sonnet-5 sometimes returns a `ThinkingBlock` as the first content block, which has no `.text`), and 49/49 unit tests stayed green the entire time it was broken. The canary would have caught it same-day instead of on the next real PR.

Feeds into Automation Watchdog like any other monitored workflow — a real failure here means the model you've configured isn't returning a response your scripts can parse, and files an alert the same way.

## Review Outcome Tracking

`ai_review.py` and `merge_advisor.py` (in the product repo, e.g. Clarion) embed a hidden metadata marker in every review comment they post:

```
<!-- ai-review-meta: {"model": "...", "verdict": "...", "pr": 123, "sha": "...", "ts": "..."} -->
```

Invisible in the rendered comment, greppable from GitHub's comment history. No new database — the PR comment is the record.

`scripts/review_outcome_report.py` (product repo) reads those markers back and correlates model choice with one concrete, imperfect proxy: did the PR need a `[ci-autofix]` or `[ai-review-apply]` commit before merge — a signal the initial code had a real problem, whether or not the review actually caught it. Run it on demand:

```
GITHUB_TOKEN=... python3 scripts/review_outcome_report.py
GITHUB_TOKEN=... python3 scripts/review_outcome_report.py --days 14
```

Pure GitHub API reads, no LLM calls — free to run whenever you want a read on how a model choice is actually doing. Not automated on a schedule; there's no alerting tied to it, it's an analysis tool you run when you want the number.

**Read this cautiously.** "Needed autofix" is a proxy, not ground truth. It won't have enough data to mean anything until real review volume accumulates, and it only catches *code* problems that needed rescue — a review that missed something subtle that shipped fine looks identical to a perfect review in this report. Read the actual flagged PRs before concluding anything about a model from the rate alone.

## Related

- [Doc Writer Agent](Doc-Writer-Agent) — the automation whose repeated silent failure motivated this page
- [Dashboard Guide](Dashboard-Guide) — where Automation Model / Review Model are configured
