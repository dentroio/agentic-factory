---
name: docs-required-parser-duplicated-across-services
description: parse_docs_required logic is duplicated in both services/status-site/wo_parser.py and services/agent-runner/prompt_builder.py and must be kept in sync manually
metadata:
  type: project
---

The `## Documentation Required` checklist parser (which extracts WO doc items and skips "None/N/A" sentinel values) is implemented twice: once in `services/status-site/wo_parser.py` (`parse_docs_required`) and once in `services/agent-runner/prompt_builder.py` (`parse_docs_required`). There's no shared import between the two services, so this is intentional duplication, not an oversight.

**Why:** status-site and agent-runner are separate deployable services without a shared library, so code can't simply be imported across them. The regex, sentinel list (`none`, `n/a`, `na`, `nil`, `-`, etc.), and checkb