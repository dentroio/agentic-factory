---
name: agent-runner-native-only-no-docker
description: agent-runner has no Docker execution path; it only runs natively via launchd, and CLI subprocesses must not inherit ANTHROPIC_API_KEY
metadata:
  type: project
---

services/agent-runner runs exclusively as a native launchd LaunchAgent (see scripts/agent-install.sh) — the Docker path was removed entirely (no Dockerfile, no compose service). It was fundamentally broken: no host Docker socket for `make build-svc` against the product's own containers, and its worktree volume wasn't a real repo clone, so the quality gate never actually chec