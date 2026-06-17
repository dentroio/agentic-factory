---
name: project-overview
description: Core project metadata — stack, architecture, repo path
metadata:
  type: project
---

**Repo:** `/path/to/repo`
**Stack:** {{language}} ({{framework}}) + {{database}} + {{frontend if any}}
**Architecture:** {{e.g., docker-compose microservices / monolith / serverless}}
**Version:** {{semver or date-based version}}

**Why:** Bootstrap entry — gives agents immediate orientation without reading the whole codebase.
**How to apply:** Use to answer "what kind of project is this?" and orient new agents at conversation start.
