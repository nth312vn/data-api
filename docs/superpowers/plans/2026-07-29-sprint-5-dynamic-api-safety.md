# Sprint 5 Dynamic API Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-memory Dynamic Route registry with PostgreSQL-backed, prefix-authorized, read-only Trino queries protected by strict SQL AST validation and typed parameter binding.

**Architecture:** Management APIs remain admin-only under `/api/v1/dynamic-routes`, while runtime queries execute through a final catch-all `GET /api/v1/{prefix}/{path:path}` router protected by the existing prefix authorization dependency. PostgreSQL stores one current row per `(prefix, path)`; `SqlSafetyValidator` produces canonical Trino SQL, and query values are cast then passed separately through SQLAlchemy parameter binding.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL JSONB, Alembic, Trino SQLAlchemy dialect, SQLGlot 30.x, pytest.

## Global Constraints

- Only one statement with a SQLGlot `Select` root is accepted; `WITH ... SELECT` is allowed.
- DDL, DML, session, privilege, transaction, command fallback, unsafe control characters, and multiple statements fail closed.
- Raw/original SQL is never executed or logged; only canonical Trino SQL is executable.
- Dynamic query values use `:name` placeholders and are never interpolated into SQL strings.
- Supported parameter types are `string`, `integer`, `float`, `boolean`, `date`, `datetime`, and `string_list`.
- `prefix` is lowercase, 3-50 characters, and matches `^[a-zA-Z0-9_.-]+$`.
- `path` is a non-empty relative path without leading/trailing slash, empty segments, `.` segments, or `..` segments.
- `(prefix, path)` is unique; `prefix="dynamic-routes"` is reserved.
- Management APIs are admin-only; execution uses `require_api_permission()` before repository lookup.
- Dynamic API does not support PII mapping and always returns `missing_mappings=[]`.
- `lab_test_result`, `pii_columns`, versioning, soft delete, and in-memory route caching are not implemented.

---

## File Map

- `app/services/query_engine/sql_safety.py`: strict Trino parser, AST policy, canonical SQL, placeholder extraction.
- `app/services/query_engine/dynamic_parameters.py`: parameter definitions, contract validation, casting, SQLAlchemy bind construction.
- `app/models/dynamic_route.py`: PostgreSQL `dynamic_routes` ORM model and computed API path.
- `app/repositories/interfaces/dynamic_route.py`: persistence protocol.
- `app/repositories/sqlalchemy/dynamic_route.py`: async SQLAlchemy CRUD.
- `app/services/query_engine/dynamic_routes.py`: create/update/delete/list/execute workflows.
- `app/api/v1/endpoints/dynamic_routes.py`: admin management endpoints.
- `app/api/v1/endpoints/dynamic_execute.py`: runtime prefix/path catch-all endpoint.
- `app/infrastructure/trino/client.py`: statement and bound-parameter execution.
- `alembic/versions/7d31b2f4a9c0_create_dynamic_routes.py`: database migration.
- `tests/test_sql_safety.py`: SQL parser and bypass matrix.
- `tests/test_dynamic_parameters.py`: typed parameter contract and injection payloads.
- `tests/test_dynamic_route_repository.py`: persistence behavior.
- `tests/test_dynamic_route_service.py`: service transactions and execution.
- `tests/test_dynamic_routes_api.py`: management/runtime routing and authorization.
- `tests/test_trino_client.py`: bound execution regression coverage.

---

### Task 1: Strict SQL Safety Validator

**Files:**
- Modify: `pyproject.toml`
- Create: `app/services/query_engine/sql_safety.py`
- Create: `tests/test_sql_safety.py`

**Interfaces:**
- Produces: `ValidatedSql(canonical_sql: str, parameter_names: frozenset[str])`.
- Produces: `SqlSafetyValidator.validate(sql: str) -> ValidatedSql`.
- Produces: `DynamicSqlError(AppError)` with stable 422 error codes.

- [ ] **Step 1: Add failing tests for accepted SQL**

Test simple `SELECT`, `WITH ... SELECT`, joins, subqueries, window functions, duplicate `:region`, and a string literal containing `DROP`.

```python
def test_validator_accepts_select_and_extracts_parameters() -> None:
    result = SqlSafetyValidator().validate(
        "WITH x AS (SELECT customer_id FROM sales WHERE region = :region) "
        "SELECT customer_id FROM x WHERE customer_id <> :customer_id"
    )
    assert result.parameter_names == frozenset({"region", "customer_id"})
    assert "DELETE" not in result.canonical_sql.upper()
```

- [ ] **Step 2: Run accepted-SQL tests and confirm import failure**

Run: `python -m pytest tests/test_sql_safety.py -v`

Expected: FAIL because `app.services.query_engine.sql_safety` does not exist.

- [ ] **Step 3: Add failing rejection matrix**

Cover empty/malformed SQL, two statements, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `DROP`, `ALTER`, `TRUNCATE`, `CALL`, `EXECUTE`, `SET`, `USE`, `GRANT`, `REVOKE`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `VALUES`, `TABLE`, SQLGlot `Command`, null byte, ASCII control characters, zero-width and bidi format characters.

```python
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DELETE FROM sales",
        "DROP TABLE sales",
        "WITH x AS (SELECT 1) DELETE FROM sales",
        "SELECT\u200b 1",
    ],
)
def test_validator_rejects_unsafe_sql(sql: str) -> None:
    with pytest.raises(DynamicSqlError):
        SqlSafetyValidator().validate(sql)
```

- [ ] **Step 4: Add SQLGlot dependency and minimal validator**

Add `"sqlglot>=30.14.0,<31.0.0"` to runtime dependencies. Implement:

```python
@dataclass(frozen=True, slots=True)
class ValidatedSql:
    canonical_sql: str
    parameter_names: frozenset[str]


class DynamicSqlError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=code,
            message=message,
        )


class SqlSafetyValidator:
    def validate(self, sql: str) -> ValidatedSql:
        _validate_characters(sql)
        statements = sqlglot.parse(sql, read="trino", error_level=ErrorLevel.RAISE)
        if len(statements) != 1:
            raise DynamicSqlError(
                "dynamic_sql_multiple_statements",
                "Exactly one SQL statement is required",
            )
        expression = statements[0]
        if not isinstance(expression, exp.Select):
            raise DynamicSqlError(
                "dynamic_sql_statement_not_allowed",
                "Only SELECT queries are allowed",
            )
        _reject_forbidden_nodes(expression)
        _strip_comments(expression)
        canonical = expression.sql(dialect="trino", comments=False)
        reparsed = sqlglot.parse_one(
            canonical,
            read="trino",
            error_level=ErrorLevel.RAISE,
        )
        if not isinstance(reparsed, exp.Select):
            raise DynamicSqlError(
                "dynamic_sql_statement_not_allowed",
                "Only SELECT queries are allowed",
            )
        names = frozenset(
            placeholder.name
            for placeholder in reparsed.find_all(exp.Placeholder)
        )
        return ValidatedSql(canonical, names)
```

Build the forbidden node tuple from SQLGlot 30.x mutation and command expression
classes (`Insert`, `Update`, `Delete`, `Merge`, `Create`, `Drop`, `Alter`,
`TruncateTable`, `Grant`, `Revoke`, `Set`, `Use`, `Transaction`, `Commit`,
`Rollback`, `Command`) and fail closed if a parsed node is not supported.

- [ ] **Step 5: Run validator tests**

Run: `python -m pytest tests/test_sql_safety.py -v`

Expected: PASS.

- [ ] **Step 6: Run lint/type checks for the validator**

Run: `python -m ruff check app/services/query_engine/sql_safety.py tests/test_sql_safety.py`

Run: `python -m mypy app/services/query_engine/sql_safety.py`

Expected: both PASS.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml app/services/query_engine/sql_safety.py tests/test_sql_safety.py
git commit -m "feat: validate dynamic SQL with Trino AST"
```

### Task 2: Typed Dynamic Parameters and Bound Statements

**Files:**
- Create: `app/services/query_engine/dynamic_parameters.py`
- Modify: `app/schemas/dynamic_route.py`
- Create: `tests/test_dynamic_parameters.py`
- Modify: `tests/test_dynamic_route_schema.py`

**Interfaces:**
- Consumes: `ValidatedSql.parameter_names`.
- Produces: `DynamicParameterType`, `DynamicParameterDefinition`.
- Produces: `validate_parameter_contract(names, definitions) -> None`.
- Produces: `cast_parameter_values(definitions, raw_values) -> dict[str, object]`.
- Produces: `build_bound_statement(sql, definitions) -> TextClause`.

- [ ] **Step 1: Replace schema tests with the new contract**

Test normalized prefix, relative path, reserved prefix, removal of `path_params` and `pii_columns`, forbidden extras, parameter definitions, and computed API path.

```python
def test_dynamic_route_write_schema_normalizes_prefix() -> None:
    request = DynamicRouteWriteRequest(
        prefix=" Power_BI ",
        path="customer-sales",
        sql="SELECT * FROM sales WHERE region = :region",
        params={"region": {"type": "string", "required": True}},
    )
    assert request.prefix == "power_bi"
    assert request.api_path == "/power_bi/customer-sales"
```

- [ ] **Step 2: Run schema tests and confirm failure**

Run: `python -m pytest tests/test_dynamic_route_schema.py -v`

Expected: FAIL because the new schema does not exist.

- [ ] **Step 3: Add failing cast and injection tests**

Test all scalar types, comma/repeated `string_list`, missing/extra parameters, invalid casts, placeholder-definition mismatch, and payload `"APAC' OR 1=1 --"` remaining a string value.

- [ ] **Step 4: Implement parameter definitions and schema**

Use:

```python
class DynamicParameterType(StrEnum):
    string = "string"
    integer = "integer"
    float = "float"
    boolean = "boolean"
    date = "date"
    datetime = "datetime"
    string_list = "string_list"


class DynamicParameterDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: DynamicParameterType
    required: bool = True
    default: str | int | float | bool | date | datetime | list[str] | None = None
    description: str = ""
```

Define `DynamicRouteWriteRequest` with `prefix`, relative `path`, `sql`, `params`, `description`, `lab_test`, and `lab_test_params`; omit `pii_columns` and `lab_test_result` from response models.

- [ ] **Step 5: Implement casting and bound statement construction**

Map scalar types to SQLAlchemy types. For `string_list`, use:

```python
bindparam(name, expanding=True, type_=String())
```

Never format or join values into SQL text.

- [ ] **Step 6: Run parameter and schema tests**

Run: `python -m pytest tests/test_dynamic_parameters.py tests/test_dynamic_route_schema.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/schemas/dynamic_route.py app/services/query_engine/dynamic_parameters.py tests/test_dynamic_parameters.py tests/test_dynamic_route_schema.py
git commit -m "feat: add typed dynamic query parameters"
```

### Task 3: Trino Bound-Parameter Execution

**Files:**
- Modify: `app/infrastructure/trino/client.py`
- Modify: `tests/test_trino_client.py`

**Interfaces:**
- Produces: `TrinoClient.execute(statement, parameters=None)`.
- Consumes: SQLAlchemy `Executable` and `Mapping[str, object]`.

- [ ] **Step 1: Add a failing driver-boundary test**

Change the fake connection to capture SQL and parameters separately:

```python
def execute(
    self,
    statement: Any,
    parameters: Mapping[str, object] | None = None,
) -> FakeResult:
    self.executions.append((str(statement), parameters))
    return FakeResult()
```

Assert the injection payload is present only in the parameter mapping.

- [ ] **Step 2: Run the Trino client test**

Run: `python -m pytest tests/test_trino_client.py -v`

Expected: FAIL because `execute()` accepts only a statement.

- [ ] **Step 3: Implement optional parameters**

Update protocol, async wrapper, sync executor, and connection call:

```python
def _execute_sync(
    self,
    statement: str | Executable,
    parameters: Mapping[str, object] | None,
) -> list[dict[str, Any]]:
    executable = text(statement) if isinstance(statement, str) else statement
    result = connection.execute(executable, parameters or {})
```

Preserve existing metadata helpers and timeout/engine disposal behavior.

- [ ] **Step 4: Run Trino tests**

Run: `python -m pytest tests/test_trino_client.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/infrastructure/trino/client.py tests/test_trino_client.py
git commit -m "feat: bind parameters in Trino client"
```

### Task 4: PostgreSQL Dynamic Route Persistence

**Files:**
- Create: `app/models/dynamic_route.py`
- Modify: `app/models/__init__.py`
- Modify: `app/infrastructure/database/base.py`
- Create: `app/repositories/interfaces/dynamic_route.py`
- Create: `app/repositories/sqlalchemy/dynamic_route.py`
- Modify: `app/dependencies/repositories.py`
- Create: `alembic/versions/7d31b2f4a9c0_create_dynamic_routes.py`
- Create: `tests/test_dynamic_route_repository.py`

**Interfaces:**
- Produces: ORM `DynamicRoute`.
- Produces: `DynamicRouteRepository.get_by_id`, `get_by_route`, `list_all`, `create`, `update`, `delete`.

- [ ] **Step 1: Write failing model/repository tests**

Use a fake async session for CRUD statement inspection and model metadata assertions for:

- composite unique `(prefix, path)`;
- lowercase prefix check;
- relative path checks;
- JSONB `parameter_definitions`;
- `created_by`/`updated_by` foreign keys;
- no `pii_columns`, `lab_test_result`, status, or version fields.

- [ ] **Step 2: Run persistence tests**

Run: `python -m pytest tests/test_dynamic_route_repository.py -v`

Expected: FAIL because model/repository do not exist.

- [ ] **Step 3: Implement model and repository**

Model core:

```python
class DynamicRoute(BaseModelMixin, Base):
    __tablename__ = "dynamic_routes"
    __table_args__ = (
        UniqueConstraint("prefix", "path", name="uq_dynamic_routes_prefix_path"),
        CheckConstraint("prefix = lower(prefix)", name="ck_dynamic_routes_prefix_lower"),
        CheckConstraint("path <> ''", name="ck_dynamic_routes_path_not_empty"),
        CheckConstraint(
            "path NOT LIKE '/%' AND path NOT LIKE '%/'",
            name="ck_dynamic_routes_path_relative",
        ),
        CheckConstraint(
            "position('//' in path) = 0",
            name="ck_dynamic_routes_path_segments",
        ),
        Index("ix_dynamic_routes_prefix", "prefix"),
        Index("ix_dynamic_routes_created_by", "created_by"),
        Index("ix_dynamic_routes_updated_at", "updated_at"),
    )
```

Use UUID foreign keys with `ON DELETE SET NULL`, PostgreSQL JSONB, and a Python `api_path` property.

- [ ] **Step 4: Add Alembic migration**

Create revision `7d31b2f4a9c0`, down revision `2d7c9a4e1b63`, with the same columns, constraints, indexes, and exact downgrade order.

- [ ] **Step 5: Verify Alembic graph and tests**

Run: `python -m alembic heads`

Expected: `7d31b2f4a9c0 (head)`.

Run: `python -m pytest tests/test_dynamic_route_repository.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add app/models app/infrastructure/database/base.py app/repositories app/dependencies/repositories.py alembic/versions/7d31b2f4a9c0_create_dynamic_routes.py tests/test_dynamic_route_repository.py
git commit -m "feat: persist dynamic route definitions"
```

### Task 5: Database-Backed Dynamic Route Service

**Files:**
- Replace: `app/services/query_engine/dynamic_routes.py`
- Modify: `app/dependencies/services.py`
- Create: `tests/test_dynamic_route_service.py`

**Interfaces:**
- Consumes: repository, UoW, Trino client, validator, parameter helpers.
- Produces: create/list/get/update/delete/execute service methods.

- [ ] **Step 1: Write failing service tests**

Cover:

- create validates before lab test and persistence;
- duplicate `(prefix, path)` raises `ConflictError`;
- update changes one row and `updated_by`;
- delete hard-deletes and commits;
- lab test failure rolls back and stores nothing;
- execute loads by `(prefix, path)`, revalidates canonical SQL, casts values, and binds values separately;
- service has no registry or PII mapper dependency.

- [ ] **Step 2: Run service tests**

Run: `python -m pytest tests/test_dynamic_route_service.py -v`

Expected: FAIL against the current registry service.

- [ ] **Step 3: Implement management workflows**

Use explicit service signatures:

```python
async def create_route(
    self,
    *,
    payload: DynamicRouteWriteRequest,
    actor: User,
) -> DynamicRoute:
    validated = self._sql_validator.validate(payload.sql)
    validate_parameter_contract(validated.parameter_names, payload.params)
    return await self._persist_new_route(
        payload=payload,
        canonical_sql=validated.canonical_sql,
        actor=actor,
    )

async def update_route(
    self,
    *,
    route_id: UUID,
    payload: DynamicRouteWriteRequest,
    actor: User,
) -> DynamicRoute:
    route = await self.get_route(route_id)
    validated = self._sql_validator.validate(payload.sql)
    validate_parameter_contract(validated.parameter_names, payload.params)
    return await self._replace_route(
        route=route,
        payload=payload,
        canonical_sql=validated.canonical_sql,
        actor=actor,
    )
```

Validate SQL and placeholder contract before querying Trino or writing the repository. For `lab_test=True`, cast `lab_test_params`, execute canonical SQL with bound values, discard rows, then persist.

- [ ] **Step 4: Implement execution workflow**

```python
async def execute_route(
    self,
    *,
    prefix: str,
    path: str,
    raw_params: QueryParams,
) -> list[dict[str, Any]]:
```

Load the route, revalidate `canonical_sql`, reconstruct definitions from JSONB, cast all parameters, build the bound statement, and call Trino. Do not call `PiiMapper`.

- [ ] **Step 5: Replace dependency wiring**

Remove `_dynamic_route_registry`, `get_dynamic_route_registry`, and PII mapper injection from Dynamic Route service wiring. Inject repository, UoW, Trino client, and a validator instance.

- [ ] **Step 6: Run service tests**

Run: `python -m pytest tests/test_dynamic_route_service.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app/services/query_engine/dynamic_routes.py app/dependencies/services.py tests/test_dynamic_route_service.py
git commit -m "feat: execute persisted dynamic routes"
```

### Task 6: Management and Runtime APIs

**Files:**
- Replace: `app/api/v1/endpoints/dynamic_routes.py`
- Create: `app/api/v1/endpoints/dynamic_execute.py`
- Modify: `app/api/v1/endpoints/__init__.py`
- Modify: `app/api/v1/router.py`
- Create: `tests/test_dynamic_routes_api.py`
- Modify: `tests/test_openapi_security.py`

**Interfaces:**
- Management: `/api/v1/dynamic-routes` plus UUID resource endpoints.
- Runtime: `GET /api/v1/{prefix}/{path:path}`.

- [ ] **Step 1: Write failing OpenAPI and route-order tests**

Assert management paths use UUID resources, runtime catch-all exists, static Power BI routes are registered before catch-all, and `/api/v1/dynamic-routes/{path}` execution no longer exists.

- [ ] **Step 2: Write failing authorization/API tests**

Cover:

- regular user cannot create/list/update/delete, including username `dynamic-routes`;
- admin can manage;
- user `power_bi` can execute `/api/v1/power_bi/customer-sales`;
- `power_bi` cannot execute `/api/v1/power_bi_extra/customer-sales`;
- authorization denial occurs before repository lookup;
- static GET collision is rejected during create/update;
- missing dynamic route returns 404;
- response is `DataRowsResponse(rows=..., missing_mappings=[])`.

- [ ] **Step 3: Run API tests**

Run: `python -m pytest tests/test_dynamic_routes_api.py tests/test_openapi_security.py -v`

Expected: FAIL against current `/dynamic-routes/{path}` router.

- [ ] **Step 4: Implement admin management router**

Use `Depends(require_roles(UserRole.admin))` on the included management router. Add POST, list GET, resource GET, PUT, and hard DELETE. Convert ORM objects to response DTOs without `pii_columns` or `lab_test_result`.

- [ ] **Step 5: Implement catch-all execution router**

```python
@router.get("/{prefix}/{path:path}", response_model=DataRowsResponse)
async def execute_dynamic_route(
    prefix: str,
    path: str,
    request: Request,
    _authorized: User = Depends(require_api_permission),
    service: DynamicRouteService = Depends(get_dynamic_route_service),
) -> DataRowsResponse:
    rows = await service.execute_route(
        prefix=prefix,
        path=path,
        raw_params=request.query_params,
    )
    return DataRowsResponse(rows=rows, missing_mappings=[])
```

Include this router last. Keep management/static routers before it.

- [ ] **Step 6: Add exact static GET collision check**

Before create/update, compute `/api/v1/{prefix}/{path}` and compare it with exact non-catch-all GET routes in `request.app.routes`. Reject with `ConflictError(code="dynamic_route_path_conflict")`.

- [ ] **Step 7: Run API tests**

Run: `python -m pytest tests/test_dynamic_routes_api.py tests/test_openapi_security.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add app/api/v1 tests/test_dynamic_routes_api.py tests/test_openapi_security.py
git commit -m "feat: expose prefix-authorized dynamic APIs"
```

### Task 7: Audit and Operational Documentation

**Files:**
- Modify: `app/services/audit_log.py`
- Modify: `app/api/v1/endpoints/dynamic_routes.py`
- Modify: `README.md`
- Modify: `docs/2-technologies.md`
- Modify: `docs/3-flows.md`
- Modify: `present.md`
- Create or modify: `tests/test_dynamic_routes_api.py`

**Interfaces:**
- Produces audit entries for create/update/delete and rejected SQL policy without storing raw SQL or values.

- [ ] **Step 1: Add failing audit tests**

Assert audit parameters contain action, prefix, path, and route ID, but not original SQL, canonical SQL, bound values, rows, or PII.

- [ ] **Step 2: Implement safe Dynamic Route audit helper**

Add:

```python
async def audit_dynamic_route_action(
    self,
    *,
    actor: User,
    action: str,
    route_id: UUID | None,
    prefix: str,
    path: str,
    allowed: bool,
    error_code: str | None = None,
) -> None:
```

Persist only safe metadata and commit through the existing UoW.

- [ ] **Step 3: Update runtime documentation**

Document the management/runtime URL split, PostgreSQL source of truth, SQLGlot policy, `:param` contract, no PII mapping, examples, read-only Trino requirement, and migration command.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_dynamic_routes_api.py tests/test_logging.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/services/audit_log.py app/api/v1/endpoints/dynamic_routes.py README.md docs/2-technologies.md docs/3-flows.md present.md tests/test_dynamic_routes_api.py
git commit -m "docs: document secure dynamic API operations"
```

### Task 8: Full Regression and Security Verification

**Files:**
- Modify only files required by failures found in this task.

- [ ] **Step 1: Run the Dynamic API security suite**

Run:

```powershell
python -m pytest tests/test_sql_safety.py tests/test_dynamic_parameters.py tests/test_dynamic_route_repository.py tests/test_dynamic_route_service.py tests/test_dynamic_routes_api.py tests/test_trino_client.py -v
```

Expected: PASS with zero failures.

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -q`

Expected: PASS with zero failures.

- [ ] **Step 3: Run lint**

Run: `python -m ruff check .`

Expected: PASS with zero errors.

- [ ] **Step 4: Run formatting check**

Run: `python -m black --check .`

Expected: PASS.

- [ ] **Step 5: Run type checking**

Run: `python -m mypy app`

Expected: PASS with zero errors.

- [ ] **Step 6: Verify migration graph**

Run: `python -m alembic heads`

Expected: only `7d31b2f4a9c0 (head)`.

- [ ] **Step 7: Inspect final diff for security regressions**

Run:

```powershell
rg -n "_resolve_sql|DynamicRouteRegistry|pii_columns|lab_test_result" app tests
git diff --check
git status --short
```

Expected: no production references to the removed registry/string replacement/PII contract; diff check clean.

- [ ] **Step 8: Commit final verification fixes if any**

```powershell
git add app tests alembic README.md docs present.md pyproject.toml
git commit -m "test: verify secure dynamic API flow"
```
