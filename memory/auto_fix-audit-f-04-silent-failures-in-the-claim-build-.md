---
name: f04-silent-failure-audit-pattern
description: Exception handlers in agent-runner's claim->build->gate->review->validate path must distinguish "ran clean" from "didn't run" — not just default to success
metadata:
  type: project
---

The agent-runner pipeline (runner.py/quality_gate.py/review_chain.py) underwent an audit (labeled "F-04") for silent-failure anti-patterns: exception handlers that catch a real error and return the same value as a genuine clean/success result, making the two indistinguishable to anyone downstream (logs, monitor thread, humans).

Key resulting invariants:
- `run_bandit()`/`run_semgrep()` in quality_gate.py now return a 3-tuple `(passed, findings, error)` instead of 2-tuple — a JSON parse failure is still non-blocking (a scanner crash isn't evidence of a vulnerability) but is surfaced via the third value, aggregated into `gate["scan_errors"]`, and posted to the WO's monitor