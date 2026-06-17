---
name: feedback-no-mock-db
description: Integration tests must hit a real database, not mocks — example feedback memory
metadata:
  type: feedback
---

Do NOT mock the database in integration tests. Use a real test database instance.

**Why:** Prior incident where mock/prod divergence masked a broken migration — tests passed but prod migration failed on deploy.

**How to apply:** When writing integration tests that touch DB logic, always use the test database (`docker-compose.test.yml` or equivalent). Unit tests that test pure business logic (no DB calls) may use mocks freely.

[[project-overview]]
