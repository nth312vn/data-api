# Sprint 4 - Chuẩn hóa query execution và logging thời gian xử lý

**Ngày tạo:** 2026-07-23
**Trạng thái:** Completed

---

## Mục tiêu sprint

Sprint này chuẩn hóa luồng thực thi các data query đi qua
`BaseQueryService` để:

1. Ghi log thời gian xử lý của mỗi lần execute, cho cả trường hợp thành công,
   thất bại và bị hủy.
2. Cho phép một query trả về nhiều loại response model khác nhau, không buộc
   mọi endpoint phải dùng `DataRowsResponse`.
3. Tách metadata phục vụ nội bộ, đặc biệt là `missing_mappings`, khỏi contract
   của HTTP response. Response model có thể có hoặc không có field PII này.
4. Giữ đầy đủ thông tin missing PII cho audit log ngay cả khi thông tin đó
   không được expose ra response.

## Phân tích codebase hiện tại

### 1. `BaseQueryService` đang phụ thuộc trực tiếp vào một response model

`_execute_route()` và hai nhánh xử lý hiện đều trả `DataRowsResponse`. Thiết kế
này khiến base service vừa thực thi query, vừa quyết định contract HTTP:

```python
return DataRowsResponse(
    rows=mapped_rows,
    missing_mappings=missing_mappings,
)
```

Khi một route cần trả `PaginatedResponse`, một model theo domain, một danh sách
thuần hoặc model không có `missing_mappings`, base service không thể tái sử dụng
mà không thêm điều kiện theo từng loại model.

### 2. `missing_mappings` đang phục vụ hai trách nhiệm khác nhau

Thông tin này hiện vừa được đưa vào response, vừa được endpoint dùng để tạo
audit log. Hai trách nhiệm không nên bị ràng buộc với nhau:

- HTTP response là contract với client và có thể khác nhau theo endpoint.
- Missing PII là execution metadata nội bộ, cần cho audit/monitoring dù response
  model có expose nó hay không.

Không nên dùng `hasattr(response, "missing_mappings")`, đọc
`model_fields` của Pydantic hoặc tự động chèn field theo tên. Các cách này biến
lỗi contract thành hành vi runtime khó kiểm tra bằng type checker.

### 3. Chưa có log duration tại ranh giới query service

`time.perf_counter()` đã được dùng ở authorization audit, nhưng
`BaseQueryService` chưa đo tổng thời gian từ lúc bắt đầu execute đến khi query,
PII mapping và build response hoàn tất.

Duration đo ở base service là **query-service duration**, không phải toàn bộ
HTTP request duration. Nó không bao gồm authentication, middleware, response
serialization và thời gian gửi response về client. Vì vậy tên event log phải
phản ánh đúng phạm vi, không dùng tên gây hiểu nhầm như `request_completed`.

## Thiết kế đề xuất

### 1. Dùng execution outcome generic

Base service trả một envelope nội bộ có generic response type:

```python
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True, slots=True)
class QueryExecutionOutcome(Generic[ResponseT]):
    response: ResponseT
    missing_mappings: tuple[MissingPiiMapping, ...] = field(
        default_factory=tuple,
    )
```

Ý nghĩa:

- `response` có thể là bất kỳ kiểu nào mà service con khai báo.
- `missing_mappings=()` nghĩa là không có mapping bị thiếu; trường hợp query
  không cấu hình PII cũng dùng giá trị này vì audit không cần phân biệt.
- Nếu monitoring cần phân biệt "không có PII" và "có PII nhưng không miss",
  dùng `pii_applied=bool(spec.pii_columns)` trong log, không dùng `None` làm
  overloaded state cho `missing_mappings`.
- Envelope chỉ tồn tại ở application/service boundary, không phải một HTTP
  response model mới.

### 2. Inject response factory thay vì introspection response model

`execute()` nhận một factory có type rõ ràng:

```python
ResponseFactory = Callable[
    [list[dict[str, Any]], tuple[MissingPiiMapping, ...]],
    ResponseT,
]


async def execute(
    self,
    *,
    spec: QuerySpec,
    response_factory: ResponseFactory[ResponseT],
) -> QueryExecutionOutcome[ResponseT]:
    ...
```

Service con quyết định cách build response tại call site:

```python
def build_data_rows_response(
    rows: list[dict[str, Any]],
    missing_mappings: tuple[MissingPiiMapping, ...],
) -> DataRowsResponse:
    return DataRowsResponse(
        rows=rows,
        missing_mappings=list(missing_mappings),
    )


def build_summary_response(
    rows: list[dict[str, Any]],
    _missing_mappings: tuple[MissingPiiMapping, ...],
) -> SummaryResponse:
    return SummaryResponse(items=rows)
```

Như vậy model có field PII sẽ chủ động nhận metadata; model không có field đó
sẽ bỏ qua một cách tường minh. Base service không import bất kỳ response model
cụ thể nào.

### 3. Endpoint nhận outcome nhưng chỉ trả response

Endpoint vẫn giữ đúng `response_model` hiện có:

```python
outcome = await service.deeplink_1(...)

if outcome.missing_mappings:
    background_tasks.add_task(
        audit_logs_service.audit_missing_mappings,
        missing_mappings=list(outcome.missing_mappings),
        ...,
    )

return outcome.response
```

Cách này bảo đảm audit missing PII không phụ thuộc vào việc response model có
field `missing_mappings`. Trong lần migrate đầu tiên, `DataRowsResponse` vẫn có
thể giữ field hiện tại để không tạo breaking API change.

### 4. Log một event có cấu trúc cho mỗi execution

Dùng monotonic clock `time.perf_counter()` và ghi duration trong nhánh success,
failure hoặc cancellation. Các field tối thiểu:

```text
query_execution_completed route_name=power_bi.deeplink_1 status=success
duration_ms=123.456 response_type=DataRowsResponse row_count=10
pii_applied=true missing_mapping_count=0
```

Khi lỗi:

```text
query_execution_completed route_name=power_bi.deeplink_1 status=failed
duration_ms=42.315 error_type=ExternalServiceError pii_applied=true
```

Quy ước:

- `INFO` cho success.
- `WARNING` cho cancellation/timeout dự kiến; `ERROR` cho exception khác.
- Re-raise nguyên exception, không đổi error contract.
- Không log SQL, query parameters, rows, token PII hoặc nội dung
  `missing_mappings`.
- `request_id` được logging formatter hiện tại tự gắn từ context, không truyền
  lại thủ công.
- Dùng một event name ổn định và các key/value cố định để log text lẫn JSON đều
  có thể search được.

Nếu cần đo toàn bộ HTTP latency cho mọi route, tạo một request-timing middleware
ở sprint riêng hoặc task mở rộng. Không gộp hai con số dưới cùng một tên metric.

## Task breakdown

### Task 1 - Tạo generic execution contract

Files:

- `app/services/query_engine/base_service.py`

Kết quả mong muốn:

- Thêm `QueryExecutionOutcome[ResponseT]` và type alias cho response factory.
- Đổi `_execute_route()` thành `execute()` hoặc giữ alias tạm thời để migrate
  an toàn.
- Base service chỉ trả generic outcome, không import `DataRowsResponse`.
- Luồng không có PII trả `missing_mappings=()` và không gọi `PiiMapper`.
- Luồng có PII map rows và lưu missing metadata trong outcome.

### Task 2 - Thêm log thời gian xử lý tại `execute()`

Files:

- `app/services/query_engine/base_service.py`
- `app/core/logging.py` nếu cần bổ sung khả năng giữ structured fields trong
  JSON formatter

Kết quả mong muốn:

- Đo bằng `time.perf_counter()`; duration log theo millisecond.
- Mỗi execution phát đúng một completion event với `status` tương ứng.
- Success log có route name, response type, row count, PII flag và số mapping
  bị thiếu.
- Failure/cancellation log có route name, duration và error type rồi re-raise.
- Không đưa dữ liệu nhạy cảm vào log.

### Task 3 - Migrate query services và endpoints

Files:

- `app/services/query_engine/users_service.py`
- `app/services/query_engine/power_bi_service.py`
- `app/api/v1/endpoints/data.py`
- `app/api/v1/endpoints/power_bi.py`
- Các query service/endpoint mới dùng `BaseQueryService`

Kết quả mong muốn:

- Mỗi service method khai báo response factory và return type cụ thể.
- Endpoint audit bằng `outcome.missing_mappings`.
- Endpoint trả `outcome.response` đúng với `response_model` FastAPI.
- Giữ nguyên JSON contract hiện tại cho các endpoint đang dùng
  `DataRowsResponse`.

### Task 4 - Bổ sung test cho generic response và timing log

Files:

- `tests/test_data_query_service.py`
- `tests/test_logging.py`
- Test endpoint liên quan nếu contract bị tác động

Kết quả mong muốn:

- Test response model có `missing_mappings`.
- Test một response model không khai báo `missing_mappings` vẫn được build và
  trả về đúng kiểu.
- Test query không có PII không gọi mapper và outcome có metadata rỗng.
- Test PII miss vẫn tạo audit metadata dù response model không expose field.
- Dùng `caplog` kiểm tra success, failure và cancellation log có duration cùng
  các field bắt buộc.
- Test xác nhận log không chứa SQL, raw PII hay response rows.
- Chạy pass `pytest`, `ruff check .` và `mypy app`.

### Task 5 - Cập nhật tài liệu vận hành

Files:

- `docs/3-flows.md`
- `README.md` nếu có phần observability/API contract liên quan

Kết quả mong muốn:

- Mô tả rõ execution outcome là contract nội bộ, không phải HTTP schema.
- Ghi rõ phạm vi của `duration_ms` và các field log có thể dùng để tra cứu.
- Ghi chú rằng việc bỏ `missing_mappings` khỏi JSON response trong tương lai là
  một API contract change riêng.

## Tiêu chí nghiệm thu

1. `BaseQueryService` không còn phụ thuộc vào response model cụ thể.
2. Có thể thêm một response model mới không có `missing_mappings` mà không sửa
   base service.
3. Missing PII vẫn được audit khi response model không expose metadata này.
4. Mọi query execution qua base service đều có duration log khi success, failed
   hoặc cancelled.
5. Log không chứa SQL, request parameter, rows hay giá trị PII.
6. API response hiện tại không thay đổi ngoài các thay đổi được phê duyệt riêng.
7. Test, lint và type checking đều pass.

## Ngoài phạm vi sprint

- Bỏ field `missing_mappings` khỏi các response đang public.
- Thay đổi schema database của audit log.
- Đo network time sau khi response body đã được gửi cho client.
- Thiết kế metrics/histogram và alert threshold cho latency; có thể thực hiện
  sau khi log field đã ổn định.
