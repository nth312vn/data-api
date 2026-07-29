# Sprint 5 Dynamic API

Sprint 5 implements the Dynamic API as a database-backed, read-only query
surface for trusted internal admins/data engineers.

## API surface

Management is admin-only:

```text
POST   /api/v1/dynamic-routes
GET    /api/v1/dynamic-routes
GET    /api/v1/dynamic-routes/{route_id}
PUT    /api/v1/dynamic-routes/{route_id}
DELETE /api/v1/dynamic-routes/{route_id}
```

Runtime execution uses the stored `prefix` and relative `path`:

```text
GET /api/v1/{prefix}/{path:path}
```

`require_api_permission()` runs before the route repository is queried. A
regular user may execute only a URL whose exact first segment equals their
username. `dynamic-routes` is reserved for management and cannot be used as a
runtime prefix. The catch-all router is registered after all static routers;
registration rejects an exact static `GET` collision.

## Registration example

```json
{
  "prefix": "power_bi",
  "path": "customer-sales",
  "description": "Sales grouped by customer",
  "sql": "WITH filtered AS (SELECT customer_id, amount FROM hive.analytics.sales WHERE region = :region AND sale_date >= :start_date) SELECT customer_id, sum(amount) AS total_amount FROM filtered GROUP BY customer_id",
  "params": {
    "region": {
      "type": "string",
      "required": true,
      "description": "Sales region"
    },
    "start_date": {
      "type": "date",
      "required": true
    }
  },
  "lab_test": true,
  "lab_test_params": {
    "region": "APAC",
    "start_date": "2026-07-01"
  }
}
```

The effective execution path is `/api/v1/power_bi/customer-sales`. The
management response exposes the original SQL for admin review and the
canonical SQL used for execution. `pii_columns` and `lab_test_result` are not
part of the contract.

## SQL safety pipeline

1. Reject null/control/Unicode format characters (except tab, CR and LF).
2. Parse exactly one statement with SQLGlot using the Trino dialect.
3. Require a `Select` root, which permits `WITH ... SELECT`.
4. Traverse the AST and reject DML, DDL, privilege/session statements,
   transaction control and command nodes.
5. Remove comments, render canonical Trino SQL and parse/validate it again.
6. Require the exact placeholder set to match the typed `params` definition.
7. Execute only canonical SQL with separately bound values.

The validator is an allowlist boundary, not a keyword blocklist. Therefore a
literal such as `SELECT 'DROP TABLE is text'` remains valid, while
`SELECT 1; DROP TABLE sales` and `WITH x AS (SELECT 1) DELETE FROM sales` are
rejected with HTTP 422 before Trino is called.

## Parameter binding and injection example

The supported types are `string`, `integer`, `float`, `boolean`, `date`,
`datetime` and `string_list`. Parameters represent values only; they cannot
represent a table, column, function, operator or SQL fragment.

For this request:

```text
GET /api/v1/power_bi/customer-sales?region=APAC%27%20OR%201%3D1%20--
```

the executable statement remains:

```sql
SELECT customer_id FROM sales WHERE region = :region
```

and Trino receives the separate mapping:

```python
{"region": "APAC' OR 1=1 --"}
```

The payload is never interpolated into SQL. `string_list` uses SQLAlchemy
expanding bind parameters; values are never joined into an `IN (...)` string.
Invalid casts, missing required values and undeclared values return HTTP 422.

## Persistence and operations

PostgreSQL is the only source of truth. `dynamic_routes` stores `prefix`,
relative `path`, `original_sql` (review only), `canonical_sql` (executable),
JSONB parameter definitions, owner IDs and timestamps. `(prefix, path)` is
unique. There is no registry cache, version, status, soft-delete column,
`pii_columns` or `lab_test_result`. DELETE is a hard delete.

Apply the migration with:

```bash
python -m alembic upgrade head
```

The Trino credential used by the application must be read-only. The
application validator is the first guard; the Trino role is the final guard.
Dynamic API responses always use `missing_mappings: []`; PII mapping is
intentionally disabled for this surface.

Dynamic management audit entries contain only action, route ID, prefix, path
and an optional safe error code. Runtime authorization audits record parameter
names, never parameter values. SQL text, bound values, result rows and PII
values are not stored in Dynamic API audit metadata.
