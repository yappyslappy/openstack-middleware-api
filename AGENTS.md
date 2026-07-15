# Repository Guidance

- Never work directly on `main`.
- The API is global across all active inventory sources.
- Do not add implicit pagination.
- `/api/v1/servers` returns every matching active server.
- `GET`, `HEAD`, and read-only `OPTIONS` routes must query MySQL inventory.
- GET queries include all active sources unless an explicit source filter is supplied.
- Always include source identity in resource responses.
- `POST`, `PUT`, `PATCH`, and `DELETE` routes may use the OpenStack client.
- Active resource rows use `is_deleted = false`; do not query resource `is_active`.
- Server host data is stored as `compute_host`.
- Child-table joins must include `inventory_source_id`.
- Do not assume child tables such as `server_tags` or `server_addresses` have numeric IDs.
- Do not globally deduplicate public images or flavors.
- Do not expose `auth_url` or credentials.
- Do not modify the sync-owned inventory schema from this API project.
- Do not add API Alembic migrations for inventory tables.
- Do not add Docker unless explicitly requested.
- Run tests, linting, formatting, and type checking before handing off changes.
