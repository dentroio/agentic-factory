---
name: placeholder-regex-vs-gh-actions-expressions
description: Placeholder-detection regex in setup_factory.py/factory_status.py must not match GitHub Actions `{{ }}` expressions
metadata:
  type: project
---

The project's placeholder convention (`{{PROJECT_NAME}}`, `{{FILL IN}}`) uses the same `{{ }}` delimiters as GitHub Actions expressions (`{{ github.workflow }}`, `${{ secrets.X }}`), which appear legitimately in ci.yml/deploy.yml.template. A naive check like `"{{" in content` or `re.findall(r"\{\{[^}]+\}\}", ...)` will match both, causing setup_factory.py to prompt for and overwrite real GH Actions expressions (destructive), and factory_status.py to falsely report unfilled placeholders.

**Why:** Real placeholders always start immediately with an uppercase letter and contain only uppercase/underscore/space; GH Actions expressions always have a leading space and lowercase/dotted content — this distinction is the only reliable differentiator, and it's not obvious from a quick glance at the regex.

**How to apply:** Any placeholder-detection/replacement logic on `.yml`/`.yml.template` files must use `\{\{[A-Z][A-Z_ ]*\}\}` (or equivalent), never a bare `{{` check or a permissive `\{\{[^}]+\}\}`. Also avoid repo-wide `find | xarg