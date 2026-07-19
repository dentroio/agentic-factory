## Clarion codebase patterns — copy these exactly, do not invent alternatives

### DB write (ALWAYS call db.commit() after execute())
```python
db.execute(text("INSERT INTO my_table (col) VALUES (:val)"), {"val": value})
db.commit()
```

### Parameterized queries (NEVER use f-strings or % formatting in SQL)
```python
# CORRECT
result = db.execute(text("SELECT * FROM endpoints WHERE mac = :mac"), {"mac": mac})
# WRONG — SQL injection risk
result = db.execute(text(f"SELECT * FROM endpoints WHERE mac = '{mac}'"))
```

### API route with auth (every new endpoint needs require_role)
```python
from clarion.api.auth import require_role

@router.get("/api/my-resource")
def get_resource(db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    ...
```

### SQLAlchemy raw query — use text(), not Query objects
```python
from sqlalchemy import text
rows = db.execute(text("SELECT id, name FROM table WHERE active = :active"), {"active": True}).fetchall()
# Access columns by name: row.id, row.name  — NOT row[0]
```

### Migration file — auto-discovered after WO-407
After WO-407 merged, `src/clarion/storage/adapter.py` auto-discovers all `.sql` files in the
`sql/migrations/` directory. Create the migration file there — do NOT add it to adapter.py's
`_MIGRATIONS` list manually. The list is now empty and adapter.py scans the directory at startup.

### Router registration — auto-registered after WO-408
After WO-408 merged, `services/data-service/main.py` auto-imports all routers registered in
`services/data-service/router_registry.py`. Add your new router to that file — do NOT append
`app.include_router(...)` calls to main.py directly.

```python
# In services/data-service/router_registry.py:
from mymodule import my_router
ROUTERS = [
    ...,
    my_router,  # add here
]
```

### Frontend route registration — auto-registered after WO-409
After WO-409 merged, `frontend/src/App.tsx` reads routes from `frontend/src/routeConfig.ts`.
Add new routes there — do NOT append `<Route ...>` elements to App.tsx directly.

```typescript
// In frontend/src/routeConfig.ts:
export const routes: RouteConfig[] = [
  ...,
  { path: "/my-page", element: <MyPage />, label: "My Page" },  // add here
];
```
