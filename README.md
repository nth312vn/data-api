# data-api

Production-oriented FastAPI backend scaffold with layered architecture, PostgreSQL, SQLAlchemy 2.0, Alembic, JWT auth, structured logging, and Docker.

## Architecture

The codebase is intentionally modular while keeping the domain model simple.

- `app/api`: HTTP routing only. Routes validate request/response shape and delegate to services.
- `app/services`: business workflows and transaction decisions. This is where login, user management, profile updates, and account deletion rules live.
- `app/repositories`: persistence contracts plus SQLAlchemy implementations. Services depend on interfaces, not ORM details.
- `app/infrastructure`: external systems such as database sessions and unit of work.
- `app/core`: shared config, security, logging, and exception handling.
- `app/dependencies`: FastAPI dependency wiring. This keeps construction logic out of route handlers and services.
- `app/models` and `app/schemas`: simple SQLAlchemy entities and Pydantic DTOs.

This structure lets future modules such as Product, Order, Payment, Notification, and AuditLog add their own model, schema, repository, service, and endpoint without changing unrelated layers.

## Data Routes and PII Mapping

Data APIs are route-specific. Clients do not submit SQL. Each endpoint owns the
Trino query it needs for its business shape, then remaps tokenized PII fields
before serving data back to clients.

Flow:

1. A client calls a route such as `GET /api/v1/data/users`.
2. The service builds the Trino SQL internally from fixed route config.
3. The service applies each route's PII token rules, then left-joins resolved
   mappings into the result with a Polars DataFrame.
4. At application startup, mapping tables are snapshotted into the independent
   in-memory PII cache using bounded, keyset-paginated queries.
5. It resolves mappings from that in-memory cache first. Request misses are loaded
   from the separate PII mapping database in bounded batches and added to the cache.
   Cache entries are keyed by PII type and token, so every source system shares the
   same mapping instead of creating a separate cache entry per system.
6. Keys absent from the PII database are held in a temporary negative cache. Until
   its TTL expires, repeated requests for only those keys do not query the PII DB.
7. The PII database can contain many mapping tables with different schemas, modeled in `app/pii_models`.
8. The main application database only stores audit logs. If a mapping is still missing, the service writes an `audit_logs` record with `event_type=pii_mapping_missing`.

Example:

```bash
curl "http://localhost:8000/api/v1/data/users?limit=100&offset=0" \
  -H "Authorization: Bearer <access_token>"
```

Power BI deeplink routes use `GET`. When dates are omitted, `start_date` defaults
to yesterday and `end_date` defaults to the current date. When `limit` is
omitted, the response is not limited. Deeplink
`segmentation`, `user_agent`, and `limit` filters run in Trino before records are
returned. `customer_id` runs after PII mapping and accepts the mapped customer
UUID. Repeated values and comma-separated values are both supported. A
`segmentation` value is matched against `segmentation['bank_name']`. A
`user_agent` value is matched against the transformed `device` value, such as
`Android`, `iOS`, or `Other`.

```bash
curl --get http://localhost:8000/api/v1/power_bi/deeplink_1 \
  -H "Authorization: Bearer <access_token>" \
  --data-urlencode "start_date=2026-06-01" \
  --data-urlencode "end_date=2026-06-02" \
  --data-urlencode "limit=1000" \
  --data-urlencode "segmentation=VCB" \
  --data-urlencode "user_agent=android" \
  --data-urlencode "customer_id=7c37bb4b-0e15-4fb9-b589-f57211ac1679"
```

```bash
curl --get http://localhost:8000/api/v1/power_bi/deeplink_2 \
  -H "Authorization: Bearer <access_token>"
```

Each PII source declares its own table and columns as a model class. These
models describe existing tables in the independent PII database; they are not
part of the main application Alembic migrations.

```python
class CustomerIdentityPiiMapping(PiiMappingModelMixin, PiiBase):
    __tablename__ = "customer_identity_map"

    __pii_type__ = "customer_id"
    __pii_token_attr__ = "customer_id"
    __pii_value_attr__ = "uuid"

    customer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    uuid: Mapped[str] = mapped_column(CHAR(36), nullable=False)
```

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

The API will be available at:

```text
http://localhost:8000
http://localhost:8000/docs
http://localhost:9000/metrics
```

Run migrations manually:

```bash
docker compose run --rm api alembic upgrade head
```

Run the API against an external PostgreSQL database:

```bash
docker compose -f docker-compose.external-db.yml up --build
```

Set `DATABASE_URL` in `.env` to the address reachable from inside the
container, for example:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@192.168.1.10:5432/data_api
```

If PostgreSQL runs on the Docker host machine, use `host.docker.internal`
instead of `localhost` or `127.0.0.1`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/data_api
```

The container waits for `DATABASE_URL` before running migrations. Tune this with
`WAIT_FOR_DATABASE`, `DATABASE_CONNECT_TIMEOUT_SECONDS`, and
`DATABASE_CONNECT_RETRY_SECONDS`. Disable startup migrations or admin bootstrap
with `RUN_MIGRATIONS=false` or `RUN_INITIAL_ADMIN=false` when the external
database is managed elsewhere.

Build through a pip proxy when needed:

```bash
PIP_PROXY=http://user:password@proxy.example.com:8080 docker compose build api
```

`docker/pip.conf` contains safe pip defaults. Keep proxy credentials in
environment variables or a local untracked config, not in git.

Run checks locally:

```bash
python -m pip install -e ".[dev]"
ruff check .
black --check .
mypy app tests
pytest
```

## Environment

Important variables:

- `DATABASE_URL`: async SQLAlchemy PostgreSQL URL.
- `PII_DATABASE_URL`: async SQLAlchemy URL for the independent PII mapping database.
- `WAIT_FOR_DATABASE`: wait for `DATABASE_URL` before startup.
- `DATABASE_CONNECT_TIMEOUT_SECONDS`: maximum startup wait for `DATABASE_URL`.
- `DATABASE_CONNECT_RETRY_SECONDS`: delay between database connection attempts.
- `RUN_MIGRATIONS`: run Alembic migrations on container startup.
- `RUN_INITIAL_ADMIN`: create or promote the initial admin on container startup.
- `JWT_SECRET_KEY`: at least 32 characters; use a high-entropy secret in production.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: short-lived access token lifetime.
- `REFRESH_TOKEN_EXPIRE_MINUTES`: refresh token lifetime.
- `CORS_ORIGINS`: comma-separated allowed origins.
- `LOG_LEVEL`, `LOG_FORMAT`: application logging level and output format.
- `LOG_FILE_PATH`: optional file path for application logs. Defaults to `/var/log/data-api/data-api.log`; leave empty to disable file logging.
- `LOG_FILE_MAX_MB`, `LOG_FILE_BACKUP_COUNT`: rotating file log size in MB and backup count.
- `METRICS_ENABLED`, `METRICS_HOST`, `METRICS_PORT`: Prometheus metrics server settings.
- `TRINO_HOST`, `TRINO_PORT`, `TRINO_USER`, `TRINO_PASSWORD`, `TRINO_HTTP_SCHEME`: Trino connection settings.
- `TRINO_REQUEST_TIMEOUT_SECONDS`: timeout for each Trino HTTP request made by the driver.
- `TRINO_QUERY_TIMEOUT_SECONDS`: maximum app-side runtime for one Trino query.
- `PII_MAPPING_SNAPSHOT_BATCH_SIZE`: maximum row/key count per PII database query.

The API request timeout, database pool settings, database statement timeouts,
and Trino retry/pool settings are configured directly in the application modules.
Database pools use `pool_pre_ping`, LIFO checkout, bounded pool waits, and
connection recycling to avoid stale long-lived connections. PostgreSQL
connections also set asyncpg connect/command timeouts and server-side
`statement_timeout` directly in the database session modules. Trino queries run
through the SQLAlchemy dialect provided by `trino[sqlalchemy]` with configurable
driver request timeout and app-side query timeout.

## API Examples

On startup, the Docker entrypoint runs the initial admin script after migrations.
The script only creates or promotes an admin when the `users` table has no
`role=admin` user. It uses `admin@example.com` / `admin` and prints a generated
temporary password in the startup log.

Create or update users manually:

```bash
bash scripts/create_user.sh \
  --username admin \
  --email admin@example.com \
  --role admin
```

When `--password` is omitted, new users get a generated temporary password.
For repeatable setup without putting the password in shell history, pass it via
environment variable:

```bash
CREATE_USER_PASSWORD='a-very-secure-password' \
bash scripts/create_user.sh \
  --username power_bi \
  --email power_bi@example.com \
  --role user
```

Reset an existing user's password:

```bash
bash scripts/reset_user_password.sh --username admin
```

When the password is omitted, the script generates and prints a temporary
password. To set it explicitly without putting the password in shell history:

```bash
RESET_USER_PASSWORD='another-secure-password' \
bash scripts/reset_user_password.sh --email admin@example.com
```

Delete an existing user:

```bash
bash scripts/delete_user.sh --username power_bi
```

The script asks for confirmation by default. For automation, pass `--yes`:

```bash
bash scripts/delete_user.sh --email power_bi@example.com --yes
```

Login:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "<temporary_password_from_startup_log>"
  }'
```

Create user as admin:

```bash
curl -X POST http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "username": "exampleuser",
    "password": "a-very-secure-password",
    "role": "user"
  }'
```

Update user as admin:

```bash
curl -X PATCH http://localhost:8000/api/v1/users/<user_id> \
  -H "Authorization: Bearer <admin_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

Delete user as admin:

```bash
curl -X DELETE http://localhost:8000/api/v1/users/<user_id> \
  -H "Authorization: Bearer <admin_access_token>"
```

Get current user:

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Refresh token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token>"}'
```

Update profile:

```bash
curl -X PATCH http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"username": "new_api_prefix"}'
```

Delete current user:

```bash
curl -X DELETE http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer <access_token>"
```

## Auth Design

Access tokens are short-lived JWTs used for API authorization. Refresh tokens are longer-lived JWTs with `typ=refresh` and a unique `jti` claim. The current implementation validates that the user still exists before rotating a token pair.

The `users.role` column is the only role source and accepts `user` or `admin`.
Admins can access every protected API. A regular user can access only the route
whose first segment exactly matches their username; for example, username
`power_bi` can access `/power_bi` and `/power_bi/*`, but not `/power_bi_extra`.

For stricter production revocation, add a refresh-token table keyed by hashed `jti`, device metadata, expiry, and revocation timestamp. That table belongs in a future `auth_tokens` module without changing the user entity.

## Operational Notes

- Exceptions are centralized and return safe JSON errors with request IDs.
- Logs are JSON-formatted and include request IDs through context variables.
- Prometheus metrics are exposed on the metrics port at `/metrics`.
- The `users` table uses UUID primary keys and unique indexes for email and username values.
- Route handlers are async and contain no business logic.
- Services decide commit boundaries through a small unit-of-work abstraction.
