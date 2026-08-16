---
name: ci-jobs-must-mirror-in-make-ci-local
description: New CI/CD jobs must be added to `make ci-local` too, and enforced via tests/unit/test_ci_local_mirrors_ci.py
metadata:
  type: project
---
The project has a self-enforcing invariant: every job in `.github/workflows/ci.yml` must have a matching Makefile target runnable via `make ci-local`, and `tests/unit/test_ci_local_mirrors_ci.py` checks both that the