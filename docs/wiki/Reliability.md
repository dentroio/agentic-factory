---
title: "Reliability & Monitoring"
description: "Catch silent Action failures, Anthropic response-shape breaks, and review model outcomes"
last_verified: 2026-08-31
covers_wos: []
doc_owner: factory-team
---

# Reliability & Monitoring

Automation that nobody watches fails invisibly. This page covers three engine tools (paste equivalents into a **product** only if that repo runs the matching workflows — never replace the engine’s live Actions with product templates).

## Automation Watchdog

`.github/workflows/automation-watchdog.yml` listens for `workflow_run` on unattended jobs (`doc-writer`, `planning-agent`, `dependabot-wo-bridge`, `api-canary`, …). On the **second consecutive failure**, it opens a GitHub issue (`automation-failure`); later failures comment on that issue. Success auto-closes it.

Uses default `GITHUB_TOKEN` only. Built on `workflow_run` so a broken `issues: labeled` trigger cannot also silence the alerter.

**Add a workflow:** put its exact `name:` in the watchdog `workflows:` list.  
**On alert:** open the linked run logs — the issue is the checklist.

Adopters: skip unless you pasted those AI workflows into the product; engine maintainers should leave this enabled.

## API Canary

`.github/workflows/api-canary.yml` runs `scripts/api_canary.py` daily: a tiny real Anthropic call with the same model resolution/parsing as other scripts (pennies/month).

Unit tests mock the API and miss response-shape breaks (e.g. a first content block without `.text`). The canary fails loudly and feeds the watchdog.

## Review outcome tracking

`ai_review.py` / `merge_advisor.py` embed hidden metadata in review comments:

```html
<!-- ai-review-meta: {"model": "...", "verdict": "...", "pr": 123, "sha": "...", "ts": "..."} -->
```

`scripts/review_outcome_report.py` correlates model vs whether a PR later needed `[ci-autofix]` / `[ai-review-apply]` — a rough proxy, not ground truth:

```bash
GITHUB_TOKEN=... python3 scripts/review_outcome_report.py
GITHUB_TOKEN=... python3 scripts/review_outcome_report.py --days 14
```

GitHub reads only — no LLM cost. Run on demand; do not treat the rate as a verdict without reading PRs.

## Related

- [Doc Writer Agent](Doc-Writer-Agent) — optional engine wiki rewriter (adopters usually skip)  
- [Dashboard Guide](Dashboard-Guide) — Automation / Review model settings  
- [GitHub Integrations](GitHub-Integrations) — which workflows live where  
- [Troubleshooting](Troubleshooting) — runtime failures on the floor  
