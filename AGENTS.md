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
- Keep OpenAPI schemas aligned with public response bodies when routes change.
- Do not include secrets, real hostnames, real project names, or real scope names in
  OpenAPI examples or documentation.
- Do not modify the sync-owned inventory schema from this API project.
- Do not add API Alembic migrations for inventory tables.
- Keep Docker production assets non-root and free of secrets.
- Do not add a production MySQL container to this API project's Compose file.
- Do not mount the Docker socket or run privileged containers for the API.
- Run tests, linting, formatting, and type checking before handing off changes.
- Run the OpenAPI export and Docker build checks when API contracts or Docker files
  change.
