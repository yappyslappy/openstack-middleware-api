# Repository Guidance

- Never work directly on `main`.
- `GET`, `HEAD`, and read-only `OPTIONS` routes must query MySQL inventory.
- `POST`, `PUT`, `PATCH`, and `DELETE` routes may use the OpenStack client.
- Every inventory database query must be scoped by `inventory_sources.scope_key`.
- Active resource rows use `is_deleted = false`; do not query resource `is_active`.
- Server host data is stored as `compute_host`.
- Child-table joins must include `inventory_source_id`.
- Do not assume child tables such as `server_tags` or `server_addresses` have numeric IDs.
- Do not modify the sync-owned inventory schema from this API project.
- Do not add API Alembic migrations for inventory tables.
- Do not add Docker unless explicitly requested.
- Run tests, linting, formatting, and type checking before handing off changes.
