# Sprint 4 - Chuẩn hóa query execution và logging thời gian xử lý

**Ngày tạo:** 2026-07-23
**Trạng thái:** Completed

---

## Mục tiêu sprint

Sprint này chuẩn hóa execution contract của query service và observability của
HTTP API để:

1. Ghi một log chung cho thời gian xử lý toàn bộ mỗi HTTP API request, cho cả
   trường hợp thành công, lỗi và timeout/cancellation.
2. Cho phép một query trả về nhiều loại response model khác nhau, không buộc
   mọi endpoint phải dùng `DataRowsResponse`.
3. Service có PII tự trả `missing_mappings`; service không có PII không bị ép
   thêm field này vào response.
4. Endpoint có PII tiếp tục dùng `missing_mappings` để ghi audit log.

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

### 2. `missing_mappings` không phải field bắt buộc của mọi response

Route có PII cần field này để client và endpoint audit biết mapping nào bị
thiếu. Route không có PII không cần trả một danh sách rỗng chỉ để thỏa contract
của base service.

Mỗi service phải khai báo response type cụ thể. Không dùng `hasattr`, đọc
`model_fields` của Pydantic hoặc tự động chèn field theo tên.

### 3. Thời gian cần đo ở HTTP middleware, không phải query service

`BaseQueryService` chỉ biết phần query và PII mapping. Nếu đo ở đây, thời gian
đăng nhập, authorization, middleware, response serialization và các endpoint
không dùng query service sẽ bị bỏ qua. Vì vậy timing phải đặt ở middleware chung,
bao quanh `call_next(request)`.

Log dùng tên `api_request_completed` và route template nếu có, không dùng query
parameters hoặc path value có thể chứa dữ liệu nhạy cảm.

## Thiết kế đề xuất

### 1. Base service chỉ giữ dependency và helper dùng chung

`BaseQueryService` không thực thi query và không build response. Nó chỉ giữ các
dependency được inject (`trino`, `pii_mapper`, `settings`, `uow`) cùng helper
reverse lookup thực sự được nhiều service dùng.

Không đặt `_execute_route()`, `execute()`, response factory hay generic outcome
trong base service. Nhờ đó base không cần biết service nào có PII hoặc dùng
response model nào.

### 2. Mỗi service tự sở hữu query, PII mapping và response

Service cụ thể gọi trực tiếp `self.trino.execute()`. Nếu route đó có PII, chính
service tạo `QuerySpec` và gọi `self.pii_mapper.map_pii_fields()`:

```python
async def list_users(...) -> DataRowsResponse:
    spec = QuerySpec(...)
    rows = await self.trino.execute(spec.statement)
    mapped_rows, missing_mappings = await self.pii_mapper.map_pii_fields(
        rows=rows,
        spec=spec,
    )
    return DataRowsResponse(
        rows=mapped_rows,
        missing_mappings=missing_mappings,
    )
```

Một service không có PII chỉ execute query và trả model của nó, không phải tạo
`missing_mappings` rỗng và không phải đi qua nhánh điều kiện trong base.

### 3. Endpoint dùng đúng contract của từng service

Endpoint có PII biết rõ response của nó có `missing_mappings` và dùng field này
để audit. Endpoint không có PII có thể trả model hoàn toàn không chứa field đó.
Không dùng reflection, generic envelope hoặc contract ngầm theo tên field.

### 4. Log một event có cấu trúc cho mỗi HTTP request

Dùng monotonic clock `time.perf_counter()` trong middleware và ghi duration ở
`finally`, để mọi request đều có event:

```text
api_request_completed method=GET path=/power-bi/deeplink_1 status_code=200
duration_ms=123.456
```

Khi lỗi HTTP, event giữ `status_code` tương ứng. Khi exception hoặc cancellation
xảy ra trước khi có response, middleware dùng `status_code=500` rồi re-raise để
exception handler hiện tại xử lý tiếp.

Quy ước:

- `INFO` cho response dưới 500; `ERROR` cho response 5xx hoặc exception chưa
  được xử lý.
- Re-raise nguyên exception, không đổi error contract.
- Không log SQL, query parameters, rows, token PII hoặc nội dung
  `missing_mappings`.
- `request_id` được logging formatter hiện tại tự gắn từ context, không truyền
  lại thủ công.
- Dùng một event name ổn định và các key/value cố định để log text lẫn JSON đều
  có thể search được.
- Không log query string, body, SQL, rows hoặc giá trị PII.

## Task breakdown

### Task 1 - Thu gọn `BaseQueryService`

Files:

- `app/services/query_engine/base_service.py`

Kết quả mong muốn:

- Bỏ `_execute_route()`, `execute()`, generic outcome và response factory.
- Base service không import hoặc tạo response model.
- Chỉ giữ dependency dùng chung và helper reverse lookup.

### Task 2 - Thêm log thời gian xử lý ở middleware chung

Files:

- `app/middlewares/request_timing.py`
- `app/main.py`

Kết quả mong muốn:

- Đo bằng `time.perf_counter()` quanh `call_next(request)`; duration log theo
  millisecond.
- Mỗi HTTP request phát đúng một event `api_request_completed`.
- Log có method, route path, status code và duration.
- Exception được re-raise nguyên trạng; timeout/cancellation vẫn được log.
- Middleware được đặt sau `RequestIDMiddleware` trong chain để log có
  `request_id`.
- Không đưa dữ liệu nhạy cảm vào log.

### Task 3 - Migrate query services và endpoints

Files:

- `app/services/query_engine/users_service.py`
- `app/services/query_engine/power_bi_service.py`
- `app/api/v1/endpoints/data.py`
- `app/api/v1/endpoints/power_bi.py`
- Các query service/endpoint mới dùng `BaseQueryService`

Kết quả mong muốn:

- Mỗi service method tự gọi `trino.execute()`.
- Service có PII tự gọi mapper và tạo response có `missing_mappings`.
- Service không có PII được trả model không chứa `missing_mappings`.
- Endpoint audit trực tiếp từ response của service có PII.
- Giữ nguyên JSON contract hiện tại cho các endpoint đang dùng
  `DataRowsResponse`.

### Task 4 - Bổ sung test cho service contract và timing log

Files:

- `tests/test_data_query_service.py`
- `tests/test_logging.py`
- Test endpoint liên quan nếu contract bị tác động

Kết quả mong muốn:

- Test từng service gọi query và map PII đúng rule của service đó.
- Test response có PII giữ `missing_mappings` để endpoint audit.
- Khi thêm service không có PII, test xác nhận service không gọi mapper và
  response không bị ép thêm field PII.
- Dùng `caplog` kiểm tra API success và error log có duration cùng các field
  bắt buộc.
- Test xác nhận log không chứa SQL, raw PII hay response rows.
- Chạy pass `pytest`, `ruff check .` và `mypy app`.

### Task 5 - Cập nhật tài liệu vận hành

Files:

- `docs/3-flows.md`
- `README.md` nếu có phần observability/API contract liên quan

Kết quả mong muốn:

- Mô tả rõ ownership query/PII mapping thuộc service cụ thể.
- Ghi rõ phạm vi của `duration_ms` và các field log có thể dùng để tra cứu.
- Ghi chú rằng việc bỏ `missing_mappings` khỏi JSON response trong tương lai là
  một API contract change riêng.

## Tiêu chí nghiệm thu

1. `BaseQueryService` không execute query, map PII hoặc build response.
2. Có thể thêm service mới với response model không có `missing_mappings` mà
   không sửa base service.
3. Service có PII vẫn trả đủ missing metadata để endpoint ghi audit.
4. Mọi HTTP API request đều có một duration log chung khi success, failed hoặc
   cancelled/timeout.
5. Log không chứa SQL, request parameter, rows hay giá trị PII.
6. API response hiện tại không thay đổi ngoài các thay đổi được phê duyệt riêng.
7. Test, lint và type checking đều pass.

## Ngoài phạm vi sprint

- Bỏ field `missing_mappings` khỏi các response đang public.
- Thay đổi schema database của audit log.
- Đo thời gian network sau khi response body đã được gửi cho client.
- Thiết kế metrics/histogram và alert threshold cho latency; có thể thực hiện
  sau khi log field đã ổn định.
