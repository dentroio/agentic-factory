---
name: orchestrator-db-connect-pitfall
description: orchestrator.py has no _db_connect() helper — always use sqlite3.connect(DB_PATH) directly
metadata:
  type: project
---

`services/orchestrator/orchestrator.py` does NOT define a `_db_connect()` helper anywhere, despite it being an intuitive name to reach for. It went undetected for a long time because DB calls are wrapped in broad `except Exception` blocks that silently converted the resulting `NameError` into a generic "not found" failure — no crash, no traceback, just a wrong-looking result.

**Why:** Rarely-exercised code paths (e.g. delete_phase/delete_milestone) had this typo copy-pasted from regex handlers into the new PM chat tool implementations, and both stayed broken silently since broad exception handling masked the NameError.

**How to apply:** In this file, always use `with sqlite3.connect(DB_PATH) as conn:` for DB access — never call `_db_connect()`. When adding new DB-touching code (especially by copying an existing pattern), grep for `_db_connect` first to confirm it isn't a phantom helper, and be wary of broad `except Exception` blocks hiding NameError/AttributeError bugs in infrequently-used actions.