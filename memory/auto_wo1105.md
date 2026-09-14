---
name: agent-runner-eslint9-flat-config-breaks-noeslintrc
description: eslint-plugin-security scan in quality_gate.py must pin eslint@8.x because eslint 9+ dropped --no-eslintrc support
metadata:
  type: project
---

quality_gate.py's `run_js_security` invokes eslint via `npx --yes -p eslint@8.57.1 -p eslint-plugin-security@3.0.1` instead of relying on the product repo's own eslint install. This is required because eslint 9+ removed `.eslintrc`/`--no-eslintrc` support in favor of flat config, and the scanner needs `--no-eslintrc` to inject its own rule set (`--rule '{"security/...": "error"}'`) without depending on the target repo's config. Using a bare `npx eslint` would silently pick up whatever eslint version is installed/cached and could break with a flat-config error.

**Why:** eslint 9's flat-config-only mode makes `--no-eslintrc` invalid, which would make the security scan fail (or worse, silently no-op) on repos/environments that already have eslint 9 cached by npx.

**How to apply:** When touching `run_js_security` or the eslint invocation, keep both `eslint` and `eslint-plugin-security` versions explicitly pinned via `-p` flags. If you need eslint 9 support, that requires a flat-config rewrite of the rule injection, not just a version bump. Also note: eslint output is only trusted if it parses as JSON starting with `[