# Sprint 2 — Tách cache PII theo từng bảng

**Ngày tạo:** 2026-07-14  
**Trạng thái:** Implementation

---

## Mục tiêu sprint

Sprint 2 chỉnh lại thiết kế PII mapping theo hướng: mỗi bảng PII có cấu trúc và cache riêng, cache nội bộ chỉ là hashmap key/value thuần, không trộn thêm `pii_type` vào key.

Các thay đổi chính:

1. Bỏ `__pii_type__` khỏi PII model/mixin.
2. Bảng account mapping có một `AccountMapInMemory` độc lập.
3. Registry chỉ dùng `mapping_name` để chọn cache/model, còn bản thân cache chỉ lưu `token -> mapped_value` và `mapped_value -> token`.
4. Mapper fail-fast khi được gọi mà không có PII rules.
5. Giá trị PII `None` được giữ nguyên; giá trị khác `None` nhưng không map được sẽ trả `null`.

---

## Phản biện trước khi làm

### 1. Bỏ `pii_type` khỏi cache là hợp lý, nhưng không nên mất registry

Nếu mỗi cache là một bảng PII độc lập, việc lưu key dạng `(pii_type, token)` trong chính cache là thừa. Nó làm cache có vẻ generic hơn, nhưng lại che đi ranh giới thật: từng bảng có schema riêng và vòng đời sync riêng.

Tuy vậy vẫn cần một registry ở tầng service để trả lời câu hỏi: rule `customer_id` hay `accountid` sẽ dùng cache/model nào. Vì vậy sprint này bỏ `pii_type` khỏi record/cache/model, nhưng giữ `mapping_name` ở biên chọn bảng.

### 2. Power BI đang dùng `accountid` nhưng model registry chỉ có `customer_id`

Đây là điểm cần lưu ý khi vận hành. Sau thay đổi này, nếu rule dùng `accountid` mà chưa khai báo cache/model tương ứng, mapper sẽ fail-fast thay vì âm thầm lookup trong cache chung. Điều này đúng với mục tiêu "mỗi bảng cache độc lập", nhưng yêu cầu team phải khai báo đầy đủ bảng PII trước khi bật route thật.

### 3. Miss mapping trả `null` an toàn hơn giữ token gốc

Hành vi cũ giữ nguyên raw token khi không map được. Điều đó dễ làm lộ token hoặc tạo dữ liệu nửa-map nửa-raw. Hành vi mới trả `null` giúp client phân biệt rõ "không có giá trị map hợp lệ", nhưng có thể ảnh hưởng dashboard đang kỳ vọng chuỗi token gốc. Cần kiểm tra downstream trước khi deploy production.

### 4. `missing_mappings` hiện vẫn còn trong response schema

Sprint này bỏ luồng collect missing trong mapper vì transformer chỉ trả value hoặc `None`. Field `missing_mappings` vẫn được giữ rỗng để tránh đổi API contract đột ngột. Nếu sau này muốn gọn hơn, có thể làm sprint riêng để bỏ field này khỏi schema/audit flow.

---

## Task breakdown

### Task 1 — Bỏ `__pii_type__` khỏi PII models

Files:

- `app/pii_models/base.py`
- `app/pii_models/account_map.py`

Kết quả mong muốn:

- `PiiMappingModelMixin` chỉ mô tả tên cột token/value/created_at.
- `CustomerIdentityPiiMapping` không còn `__pii_type__`.
- Registry model dùng mapping name tường minh:

```python
PII_MAPPING_MODELS = {
    "customer_id": CustomerIdentityPiiMapping,
}
```

### Task 2 — Đổi cache thành key/value thuần

File:

- `app/services/account_map_in_memory.py`

Kết quả mong muốn:

- `AccountMapInMemory.hashmap_token_to_value: dict[str, str]`
- `AccountMapInMemory.hashmap_value_to_token: dict[str, str]`
- Thêm `PiiMappingCacheRegistry` để giữ nhiều cache độc lập theo `mapping_name`.

### Task 3 — Đổi repository/snapshot sang mapping name

Files:

- `app/repositories/interfaces/pii_mapping.py`
- `app/repositories/sqlalchemy/account_map.py`
- `app/services/pii_mapping_snapshot.py`
- `app/services/pii_cache_sync.py`
- `app/dependencies/services.py`

Kết quả mong muốn:

- `PiiMappingRecord` không còn `pii_type`.
- `get_many(mapping_name=..., tokens=...)`.
- `get_mappings_batch(mapping_name=..., limit=..., offset=..., since=...)`.
- Snapshot/incremental sync load từng mapping name vào cache tương ứng.

### Task 4 — Đổi mapper/transformer theo null-on-miss

Files:

- `app/services/query_engine/pii_rules.py`
- `app/services/query_engine/pii_mapper.py`
- `app/services/query_engine/base_service.py`
- `app/services/query_engine/dynamic_routes.py`

Kết quả mong muốn:

- `PiiMapper.map_pii_fields` raise `ValueError` nếu spec không có PII rules.
- Nếu row không có column thì bỏ qua.
- Nếu `row[column_name] is None` thì giữ nguyên `None`, không gọi transformer.
- Nếu transformer không map được thì trả `None`.
- Mapper set cột thành `None` khi transformer trả `None`, hoặc set mapped value khi map được.

### Task 5 — Cập nhật test

Files:

- `tests/test_account_map_in_memory.py`
- `tests/test_pii_mapping_repository.py`
- `tests/test_data_query_service.py`

Kết quả mong muốn:

- Test cache khẳng định hashmap thuần `str -> str`.
- Test registry khẳng định hai bảng PII có cache độc lập.
- Test mapper khẳng định miss mapping trả `null`.
- Test mapper khẳng định gọi không có rules sẽ raise exception.
