# data-api

Production-oriented FastAPI backend scaffold with layered architecture, PostgreSQL, SQLAlchemy 2.0, Alembic, JWT auth, structured logging, and Docker.

## Architecture

The codebase is intentionally modular while keeping the domain model simple.

- `app/api`: HTTP routing only. Routes validate request/response shape and delegate to services.
- `app/services`: business workflows and transaction decisions. This is where registration, login, profile updates, and account deletion rules live.
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
3. The service collects route-owned PII token fields such as `email_token`.
4. It resolves mappings from the in-memory cache first.
5. Cache misses are loaded from the separate PII mapping database.
6. The PII database can contain many mapping tables with different schemas, modeled in `app/pii_models`.
7. The main application database only stores audit logs. If a mapping is still missing, the service writes an `audit_logs` record with `event_type=pii_mapping_missing`.

Example:

```bash
curl "http://localhost:8000/api/v1/data/users?limit=100&offset=0" \
  -H "Authorization: Bearer <access_token>"
```

Each PII source declares its own table and columns as a model class. These
models describe existing tables in the independent PII database; they are not
part of the main application Alembic migrations.

```python
class EmailPiiMapping(PiiMappingModelMixin, PiiBase):
    __tablename__ = "pii_email_lookup"

    __pii_type__ = "email_token"
    __pii_token_attr__ = "email_hash"
    __pii_value_attr__ = "email_address"
    __pii_source_attr__ = "system_code"

    email_hash: Mapped[str] = mapped_column(String(512), primary_key=True)
    system_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
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
```

Run migrations manually:

```bash
docker compose run --rm api alembic upgrade head
```

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
- `JWT_SECRET_KEY`: at least 32 characters; use a high-entropy secret in production.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: short-lived access token lifetime.
- `REFRESH_TOKEN_EXPIRE_MINUTES`: refresh token lifetime.
- `CORS_ORIGINS`: comma-separated allowed origins.
- `TRINO_HOST`, `TRINO_PORT`, `TRINO_USER`, `TRINO_HTTP_SCHEME`: Trino connection settings.
- `TRINO_CATALOG`, `TRINO_SCHEMA`, `TRINO_USERS_TABLE`: Trino namespace and table name used when building route-owned queries.
- `PII_MAPPING_CACHE_MAX_SIZE`: maximum number of mapping entries held in process memory.

## API Examples

Register:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "username": "exampleuser",
    "password": "a-very-secure-password",
    "full_name": "Example User"
  }'
```

Login:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "a-very-secure-password"
  }'
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
  -d '{"full_name": "Updated Name"}'
```

Delete current user:

```bash
curl -X DELETE http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer <access_token>"
```

## Auth Design

Access tokens are short-lived JWTs used for API authorization. Refresh tokens are longer-lived JWTs with `typ=refresh` and a unique `jti` claim. The current implementation validates that the user still exists and is active before rotating a token pair.

For stricter production revocation, add a refresh-token table keyed by hashed `jti`, device metadata, expiry, and revocation timestamp. That table belongs in a future `auth_tokens` module without changing the user entity.

## Operational Notes

- Exceptions are centralized and return safe JSON errors with request IDs.
- Logs are JSON-formatted and include request IDs through context variables.
- The `users` table uses UUID primary keys and unique indexes for email and username values.
- Route handlers are async and contain no business logic.
- Services decide commit boundaries through a small unit-of-work abstraction.
