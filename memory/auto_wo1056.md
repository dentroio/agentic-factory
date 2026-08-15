---
name: af-12-secret-handling-pattern
description: Factory secrets (Keychain/OAuth/LaunchAgent env vars) must never touch disk world-readable or stdout — use 0600 temp files, plistlib, and compose-with-env.sh
metadata:
  type: project
---

This repo has an explicit security invariant (tracked as AF-12) that factory secrets (Keychain values, GDrive OAuth tokens, agent API keys in LaunchAgent plists) must never be written to disk in a world-readable way, printed to stdout/logs,