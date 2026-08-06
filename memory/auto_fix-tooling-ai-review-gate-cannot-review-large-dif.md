---
name: ci-local-must-mirror-ci-yml
description: make ci-local exists and is tested to mirror ci.yml's pytest invocation exactly — changing one without the other breaks a test
metadata:
  type: project
---

`make ci-local` now exists in the Makefile (previously only in Makefile.template, causing "No rule to make target" for every agent following AGENT_PROCESS.md/README.md/CLAUDE.md/AGENTS.md instructions). It composes `test` and `pre-pr-check` targets and is guarded by `tests