# Sprint 5 - Làm cứng SQL safety cho Dynamic API

**Ngày tạo:** 2026-07-29
**Trạng thái:** Draft - chờ review

---

## Mục tiêu sprint

Sprint này làm cứng luồng định nghĩa và thực thi SQL của Dynamic API để:

1. Chỉ admin/data engineer nội bộ được phép đăng ký, xem cấu hình và xóa
   Dynamic Route.
2. Chỉ chấp nhận đúng một câu truy vấn read-only có dạng `SELECT` hoặc
   `WITH ... SELECT`.
3. Chặn DDL, DML, command, multi-statement và các biến thể cố tình che giấu
   bằng comment, whitespace hoặc ký tự điều khiển.
4. Bỏ cơ chế thay chuỗi `{param}` và chuyển sang typed parameter binding với
   placeholder `:param`.
5. Parse SQL thành AST theo dialect Trino, validate fail-closed và chỉ thực thi
   canonical SQL sinh lại từ AST.
6. Dùng cùng một validation/execution pipeline cho lab test và request thật.

## Threat model và quyết định đã chốt

### Người định nghĩa SQL

Người định nghĩa SQL là admin hoặc data engineer nội bộ, được tin cậy về mục
đích sử dụng. Hệ thống vẫn phải bảo vệ trước:

- Sai sót vô tình làm thay đổi dữ liệu.
- SQL sai cú pháp hoặc chứa nhiều statement.
- Ký tự đặc biệt, comment hoặc cú pháp lạ dùng để vượt qua kiểm tra từ khóa.
- SQL injection từ query parameters do client gửi khi thực thi Dynamic Route.

### Phạm vi SQL được phép

Chỉ cho phép một truy vấn có root AST là `SELECT`. `WITH ... SELECT` được phép
vì CTE thuộc cây của truy vấn `SELECT`.

Các statement read-only khác như `SHOW`, `DESCRIBE`, `EXPLAIN`, `VALUES` và
`TABLE` không thuộc contract sprint này và phải bị từ chối. `UNION`,
`INTERSECT` và `EXCEPT` cũng chưa được hỗ trợ nếu root AST không phải
`SELECT`; việc mở rộng phải được review như một thay đổi policy riêng.

### Không dùng allowlist dữ liệu

Sprint này không giới hạn catalog, schema, table hoặc column ở application
layer. Đây là quyết định có chủ đích vì data engineer cần viết query linh hoạt.

Rủi ro còn lại được chấp nhận: một `SELECT` hợp lệ vẫn có thể đọc mọi dữ liệu
mà Trino credential có quyền truy cập. Vì vậy Trino credential dùng bởi Data API
phải được cấu hình read-only ở Trino. Application validator không thay thế cơ
chế phân quyền của Trino.

### Breaking change được chấp nhận

Contract `{param}` và `path_params: list[str]` hiện tại bị loại bỏ. Dynamic Route
mới dùng placeholder `:param` và một object `params` khai báo kiểu dữ liệu.

Dynamic Route hiện chỉ nằm trong memory nên không cần database migration. Sau
khi restart/deploy, route phải được đăng ký lại theo contract mới.

## Phân tích codebase hiện tại

### 1. SQL được nhận và lưu mà không parse

`CreateDynamicRouteRequest.sql` nhận chuỗi tự do. `DynamicRouteService` tạo
config và đăng ký thẳng vào `DynamicRouteRegistry`. Nếu không bật lab test,
syntax và loại statement không được kiểm tra trước khi route sẵn sàng phục vụ.

Hệ quả:

- `UPDATE`, `DELETE`, `DROP`, `CALL` hoặc nhiều statement có thể được lưu.
- SQL lỗi chỉ xuất hiện khi client gọi route.
- Không có canonical representation để biết chính xác statement nào sẽ chạy.

### 2. Parameter hiện được chèn bằng string replacement

`DynamicRouteService._resolve_sql()` duyệt query parameters, escape dấu nháy
đơn rồi thay `{param}` trực tiếp trong SQL template.

Cách này có các vấn đề:

- Parameter declaration `path_params` không được dùng để validate input.
- Thiếu parameter khiến placeholder còn nguyên và được gửi xuống Trino.
- Parameter thừa bị bỏ qua ngầm nếu template không chứa placeholder tương ứng.
- Mọi giá trị đều bị đặt trong dấu nháy nên không có type contract.
- An toàn phụ thuộc vào logic quote thủ công và vị trí placeholder trong SQL.
- Placeholder đặt ở identifier, expression hoặc clause có thể thay đổi cấu trúc
  query theo cách application không kiểm soát được.

### 3. Lab test và runtime chưa có security boundary chung

Lab test và runtime cùng gọi `_resolve_sql()`, nhưng không có một object kết quả
validation bất biến để bảo đảm SQL đã qua cùng một policy. Lab test cũng không
bắt buộc, nên không thể được dùng như security gate.

### 4. Quyền quản lý Dynamic Route chưa phải admin-only

Router hiện dùng dependency `require_api_permission` chung cho create, list,
execute và delete. Endpoint quản lý route chưa khai báo rõ `require_roles(admin)`.
Điều này không thể hiện đúng threat model rằng chỉ admin/data engineer nội bộ
được định nghĩa SQL.

## Kiến trúc đề xuất

### 1. `SqlSafetyValidator`

Tạo một component độc lập chịu trách nhiệm biến raw SQL thành một kết quả đã
được xác thực:

```text
raw SQL
  -> kiểm tra ký tự đầu vào
  -> parse bằng sqlglot với dialect Trino
  -> yêu cầu đúng một statement
  -> kiểm tra root và toàn bộ AST
  -> sinh canonical Trino SQL
  -> parse và validate lại canonical SQL
  -> trả ValidatedSql
```

Interface mong muốn:

```python
@dataclass(frozen=True, slots=True)
class ValidatedSql:
    original_sql: str
    canonical_sql: str
    parameter_names: frozenset[str]


class SqlSafetyValidator:
    def validate(self, sql: str) -> ValidatedSql: ...
```

`ValidatedSql` là output duy nhất được phép chuyển sang execution layer. Trino
client không nhận raw SQL từ request đăng ký Dynamic Route.

`original_sql` chỉ được giữ trong config để admin xem lại qua management API.
Field này không được ghi vào application log/audit log và không được truyền cho
Trino client.

### 2. Strict parsing theo dialect Trino

Dùng `sqlglot` và chỉ định rõ dialect Trino. Parser phải chạy ở chế độ báo lỗi
nghiêm ngặt; không dùng generic dialect hoặc best-effort transpilation.

Validation phải fail-closed:

- Parse error: từ chối.
- Không có statement: từ chối.
- Nhiều hơn một statement: từ chối.
- Parser fallback thành `Command` hoặc node không hỗ trợ: từ chối.
- Root không phải `Select`: từ chối.
- Canonical SQL không thể parse lại thành cùng policy: từ chối.

Không dùng regex/blocklist từ khóa làm security boundary. Regex có thể được dùng
cho input hygiene hoặc thông báo lỗi, nhưng quyết định allow/deny phải dựa trên
token/AST.

### 3. AST policy read-only

Sau khi xác nhận root là `Select`, validator duyệt toàn bộ cây và từ chối nếu
phát hiện node có side effect hoặc command, bao gồm tối thiểu:

- DML: `Insert`, `Update`, `Delete`, `Merge`.
- DDL: `Create`, `Drop`, `Alter`, `Truncate`.
- Privilege/session: `Grant`, `Revoke`, `Set`, `Use`.
- Procedure/command: `Call`, `Execute`, `Command`.
- Transaction control và node statement không thuộc query `Select`.

Danh sách node bị cấm phải được tập trung trong `SqlSafetyValidator`, có test
policy riêng và không rải điều kiện theo endpoint/service.

Root allowlist và forbidden-node traversal phải cùng tồn tại. Chỉ kiểm tra root
không đủ nếu parser biểu diễn một cấu trúc nguy hiểm trong subtree.

### 4. Ký tự lạ, comment và statement delimiter

Trước khi parse, validator từ chối:

- Null byte.
- ASCII control characters ngoài tab, CR và LF.
- Unicode format characters như zero-width và bidirectional override.

Comment ngoài string literal không có giá trị runtime cho Dynamic Route và phải
được loại khỏi AST trước khi render. Không dựa vào behavior mặc định của
generator vì parser/generator có thể giữ comment theo best-effort. Canonical SQL
không được chứa comment.

Statement delimiter chỉ được chấp nhận như dấu kết thúc duy nhất ở cuối query
nếu parser vẫn trả đúng một statement. Bất kỳ token hoặc statement nào sau đó
đều bị từ chối.

Không normalize toàn bộ SQL bằng Unicode NFKC vì thao tác này có thể thay đổi
string literal hoặc quoted identifier. Ký tự format/điều khiển nguy hiểm được
từ chối rõ ràng thay vì âm thầm biến đổi.

### 5. Canonical SQL là executable source

Sau AST validation, hệ thống render lại query bằng Trino generator. Runtime chỉ
execute `canonical_sql`; tuyệt đối không execute `original_sql`.

Registry lưu:

- `original_sql`: chỉ phục vụ admin review qua management API, không được
  execute hoặc ghi vào log/audit.
- `canonical_sql`: nguồn duy nhất cho lab test và runtime.
- `parameter_definitions`: contract typed parameters.
- Metadata route và PII config hiện có.

Trước mỗi execution, canonical SQL được parse và validate lại. Việc validate lại
bảo vệ khi config source thay đổi trong tương lai, ví dụ chuyển registry sang
database hoặc import config từ file.

### 6. Typed parameter contract

Thay:

```json
{
  "sql": "SELECT * FROM sales WHERE region = {region}",
  "path_params": ["region"]
}
```

bằng:

```json
{
  "sql": "SELECT * FROM sales WHERE region = :region",
  "params": {
    "region": {
      "type": "string",
      "required": true
    }
  }
}
```

Các kiểu được hỗ trợ trong sprint:

- `string`
- `integer`
- `float`
- `boolean`
- `date`
- `datetime`
- `string_list`

Mỗi definition có:

- `type`: bắt buộc.
- `required`: mặc định `true`.
- `default`: chỉ hợp lệ khi `required=false` và phải cast được về `type`.
- `description`: tùy chọn, chỉ là metadata.

Quy tắc contract:

- Tên parameter phải khớp `^[A-Za-z_][A-Za-z0-9_]*$`.
- Tập placeholder trong SQL phải bằng chính xác tập key trong `params`.
- Placeholder thiếu definition: từ chối đăng ký.
- Definition không được dùng trong SQL: từ chối đăng ký.
- Duplicate placeholder trong SQL được phép và dùng cùng một bound value.
- Client thiếu parameter bắt buộc: trả validation error.
- Client gửi parameter không khai báo: trả validation error.
- Parameter chỉ đại diện cho value; không dùng cho table, column, function,
  sort direction hoặc một đoạn SQL.

`string_list` chỉ được dùng ở vị trí được driver hỗ trợ expanding bind. Sprint
phải có integration-style test với Trino SQLAlchemy dialect chứng minh danh sách
được truyền như bound values, không được tự nối thành chuỗi `IN (...)`. Nếu
driver/dialect đang dùng không vượt qua test này, `string_list` phải bị từ chối
và được đưa ra khỏi scope implementation thay vì fallback sang string
interpolation.

### 7. Parameter binding ở Trino client

Mở rộng contract của `TrinoClient` để statement và values đi riêng:

```python
async def execute(
    self,
    statement: str | Executable,
    parameters: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]: ...
```

`TrinoPythonClient` dùng SQLAlchemy `text(canonical_sql)` cùng typed
`bindparam()` và gọi:

```python
connection.execute(statement, parameters)
```

Không log hoặc render bound value vào SQL. Test phải capture riêng statement và
parameters để chứng minh payload như:

```text
APAC' OR 1=1 --
```

vẫn là một string value, không xuất hiện trong executable SQL text.

### 8. Authorization

Các endpoint quản lý phải admin-only:

- `POST /api/v1/dynamic-routes`
- `GET /api/v1/dynamic-routes`
- `DELETE /api/v1/dynamic-routes/{path}`

Endpoint execute tiếp tục dùng API authorization hiện tại:

- `GET /api/v1/dynamic-routes/{path}`

Project hiện chỉ có role `admin` và `user`, vì vậy sprint dùng role `admin`.
Thiết kế role `data_engineer` riêng nằm ngoài phạm vi.

### 9. Một pipeline cho create, lab test và execute

Luồng đăng ký:

```text
admin request
  -> Pydantic schema validation
  -> SqlSafetyValidator
  -> ParameterContractValidator
  -> optional lab test bằng canonical SQL + bound values
  -> register config
```

Nếu lab test được bật, route chỉ được register sau khi validation và query đều
thành công. Lab test không có đường execute raw SQL riêng.

Luồng runtime:

```text
client request
  -> authorization
  -> registry lookup
  -> revalidate canonical SQL
  -> validate/cast query parameters
  -> execute canonical SQL + bound values
  -> PII mapping
  -> response/audit hiện có
```

## Error handling

### Registration errors

SQL policy và parameter contract errors trả HTTP `422` với mã lỗi ổn định:

- `DYNAMIC_SQL_PARSE_ERROR`
- `DYNAMIC_SQL_MULTIPLE_STATEMENTS`
- `DYNAMIC_SQL_STATEMENT_NOT_ALLOWED`
- `DYNAMIC_SQL_UNSAFE_CHARACTER`
- `DYNAMIC_SQL_PARAMETER_MISMATCH`
- `DYNAMIC_SQL_PARAMETER_POSITION_NOT_ALLOWED`

Response chỉ chứa mô tả an toàn, line/column nếu parser cung cấp và tên
parameter liên quan. Không trả stack trace hoặc toàn bộ SQL trong error message.

### Runtime parameter errors

Runtime trả HTTP `422` cho:

- Thiếu parameter bắt buộc.
- Parameter thừa.
- Không cast được về type đã đăng ký.
- Danh sách rỗng ở vị trí không được hỗ trợ.

Không gọi Trino nếu parameter validation thất bại.

### Trino errors

Syntax hoặc semantic error còn lại từ Trino đi qua exception handling hiện tại.
Log được phép chứa route name, request ID và error category; không log canonical
SQL, bound parameters, result rows hoặc raw PII.

### Audit

Ghi audit cho:

- Admin tạo hoặc xóa Dynamic Route.
- SQL registration bị từ chối, với policy error code.
- Runtime parameter validation bị từ chối.
- Missing PII mapping theo flow hiện tại.

Không lưu raw parameter value trong audit record của SQL safety.

## Task breakdown

### Task 1 - Thêm dependency và xây dựng SQL safety policy

Files:

- `pyproject.toml`
- `app/services/query_engine/sql_safety.py` hoặc module tương đương
- `tests/test_sql_safety.py`

Kết quả mong muốn:

- Thêm `sqlglot` làm runtime dependency.
- Parse nghiêm ngặt bằng dialect Trino.
- Trả `ValidatedSql` bất biến.
- Enforce single statement, `Select` root và forbidden-node traversal.
- Reject parser fallback `Command`, unsafe control/format characters.
- Sinh canonical SQL không chứa comment.
- Parse và validate lại canonical SQL trước khi trả kết quả.

### Task 2 - Thay schema Dynamic Route bằng typed parameter contract

Files:

- `app/schemas/dynamic_route.py`
- `app/services/query_engine/dynamic_routes.py`
- `tests/test_dynamic_route_schema.py`

Kết quả mong muốn:

- Bỏ `path_params`.
- Thêm `params: dict[str, DynamicParameterDefinition]`.
- Hỗ trợ các type đã chốt và validate `required/default`.
- Chỉ hỗ trợ placeholder `:name`.
- Placeholder và definition phải khớp tuyệt đối.
- Legacy `{param}` bị từ chối với error rõ ràng.

### Task 3 - Thêm parameter binding vào Trino client

Files:

- `app/infrastructure/trino/client.py`
- Các fake Trino client trong tests
- `tests/test_trino_client.py`

Kết quả mong muốn:

- `execute()` nhận parameters riêng.
- Dùng SQLAlchemy `text()` và typed `bindparam()`.
- Không còn quote/replace parameter thủ công.
- Có test scalar types và expanding `string_list`.
- Có test injection payload chứa quote, comment và SQL fragment nhưng statement
  gửi xuống driver không thay đổi.

### Task 4 - Tích hợp validation pipeline vào Dynamic Route service

Files:

- `app/services/query_engine/dynamic_routes.py`
- `app/dependencies/services.py`
- `app/api/v1/endpoints/dynamic_routes.py`
- Test service/API Dynamic Route mới

Kết quả mong muốn:

- Create route validate SQL và parameter contract trước lab test/register.
- Registry lưu original SQL, canonical SQL và typed definitions.
- Lab test và runtime dùng canonical SQL cùng bound parameters.
- Runtime validate lại canonical SQL.
- Xóa `_resolve_sql()` và mọi string replacement.
- Existing PII mapping/response contract được giữ nguyên.

### Task 5 - Siết quyền quản lý Dynamic Route

Files:

- `app/api/v1/endpoints/dynamic_routes.py`
- `app/dependencies/auth.py` nếu cần helper hiện có
- Test authorization liên quan

Kết quả mong muốn:

- Create/list/delete chỉ cho role `admin`.
- Execute giữ API permission flow hiện tại.
- Request bị từ chối trước khi parse hoặc execute SQL.
- Có test user thường không thể xem original/canonical SQL.

### Task 6 - Bổ sung security test matrix

Files:

- `tests/test_sql_safety.py`
- `tests/test_dynamic_routes_api.py`
- `tests/test_trino_client.py`

Nhóm test hợp lệ:

- Simple `SELECT`.
- `WITH ... SELECT`.
- Join, subquery, window function và Trino expression hợp lệ.
- String literal chứa từ `DROP`, `DELETE` hoặc dấu chấm phẩy.
- Duplicate placeholder dùng chung một value.

Nhóm test bị từ chối:

- Empty SQL và malformed SQL.
- Hai hoặc nhiều statement.
- `INSERT`, `UPDATE`, `DELETE`, `MERGE`.
- `CREATE`, `DROP`, `ALTER`, `TRUNCATE`.
- `CALL`, `EXECUTE`, `SET`, `USE`, `GRANT`, `REVOKE`.
- `SHOW`, `DESCRIBE`, `EXPLAIN`, `VALUES`, `TABLE`.
- Parser fallback thành `Command`.
- Null byte, zero-width và bidirectional control character.
- DML/DDL ở mixed case, có whitespace hoặc comment bất thường.
- Legacy `{param}`.
- Placeholder dùng làm identifier hoặc SQL fragment.

Nhóm parameter injection:

- Quote đơn và quote kép.
- `OR 1=1`.
- Inline/block comment marker.
- Semicolon và statement fragment.
- Unicode string.
- Empty, missing, extra và invalid typed value.

### Task 7 - Cập nhật tài liệu vận hành

Files:

- `README.md`
- `docs/2-technologies.md`
- `docs/3-flows.md`
- Tài liệu Dynamic API mới nếu cần

Kết quả mong muốn:

- Mô tả contract `:param` và typed parameter definitions.
- Mô tả single `SELECT`/`WITH ... SELECT` policy.
- Ghi rõ original SQL không bao giờ được execute.
- Ghi rõ parser là application guard, Trino read-only role là lớp cuối.
- Cung cấp example đăng ký, lab test, execute và error response.
- Không mô tả allowlist catalog/schema/table vì không thuộc policy đã chốt.

## Ví dụ contract mục tiêu

### Đăng ký route

```json
{
  "path": "reports/customer-sales",
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
  "pii_columns": ["customer_id"],
  "lab_test": true,
  "lab_test_params": {
    "region": "APAC",
    "start_date": "2026-07-01"
  }
}
```

### Execute route

```http
GET /api/v1/dynamic-routes/reports/customer-sales?region=APAC&start_date=2026-07-01
Authorization: Bearer <access_token>
```

Nếu client gửi:

```text
region=APAC' OR 1=1 --
```

giá trị này vẫn được bind như một string duy nhất. Nó không được nối vào
canonical SQL và không thể tạo thêm AST node hoặc thay đổi điều kiện query.

## Tiêu chí nghiệm thu

1. Không có code path nào của Dynamic API execute raw/original SQL.
2. Chỉ đúng một `SELECT` hoặc `WITH ... SELECT` được đăng ký.
3. Multi-statement, DML, DDL, command và parser fallback đều bị từ chối trước
   khi gọi Trino.
4. Ký tự điều khiển/format nguy hiểm bị từ chối; comment không tồn tại trong
   canonical executable SQL.
5. Tập placeholder bằng chính xác tập typed parameter definitions.
6. Query parameter được cast và truyền tách biệt khỏi SQL statement.
7. Injection payload không xuất hiện trong executable SQL text.
8. Lab test và runtime dùng cùng validator, canonicalizer và binder.
9. Create/list/delete Dynamic Route chỉ cho admin.
10. Trino credential triển khai production được xác nhận read-only.
11. Existing PII mapping và `DataRowsResponse` không thay đổi ngoài các error
    contract được nêu trong sprint.
12. `pytest`, `ruff check .` và `mypy app` đều pass.

## Ngoài phạm vi sprint

- Allowlist/denylist catalog, schema, table hoặc column.
- Phân tích quyền truy cập dữ liệu theo tenant ở SQL AST.
- Tạo role `data_engineer` mới trong application.
- Persist Dynamic Route vào database hoặc đồng bộ registry giữa nhiều worker.
- Cho phép DDL/DML dù là admin.
- Cho phép dynamic identifier, raw SQL fragment hoặc custom expression từ query
  parameter.
- Hỗ trợ `SHOW`, `DESCRIBE`, `EXPLAIN`, `VALUES`, `TABLE`, `UNION`,
  `INTERSECT` hoặc `EXCEPT`.
- Chứng minh an toàn tuyệt đối trước bug của parser/driver; Trino read-only role
  vẫn là control bắt buộc.
- Tự động thêm `LIMIT`, phân tích query cost hoặc chặn query đọc quá nhiều dữ
  liệu; timeout hiện tại tiếp tục được áp dụng.
