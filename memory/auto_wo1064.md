---
name: ci-gate-no-empty-suite-bypass
description: CI/Makefile test gate must fail on empty test suites — no exit-5 tolerance, requires >=20 unit test files
metadata:
  type: project
---

The CI gate (`ci.yml` and the Makefile `test`/`ci-local` targets) previously tolerated pytest exit code 5 ("no tests collected") as a non-failure, reasoning it wasn't a "test failure." This was a loophole: deleting or renaming `tests/unit/` would make the gate pass. It's now hard-invariant that exit 5 must fail, and the gate additionally asserts `tests/unit/` contains at least 20 test files (`-ge 20` check) before running, so an empty/gutted suite cannot go green.

**Why:** A previous "reasonable-sounding" exception (tolerate exit 5) turned into an unintended bypass — same failure mode CI gates are meant to prevent (`|| true`), just less obvious.

**How to apply:** Never add `eq 5` / exit-code tolerances back into `ci.yml` or the Makefile test targets. If you touch the test-count threshold, keep or raise `-ge 20`, and check `tests/unit/test_ci_local_mirrors_ci.py` for the tests enforc