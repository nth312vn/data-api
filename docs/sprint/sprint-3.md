# Sprint 3 - Đơn giản hóa PII mapping cho customer

**Ngày tạo:** 2026-07-14  
**Trạng thái:** Completed

---

## Mục tiêu sprint

Hệ thống hiện chỉ có một nguồn PII là customer. Sprint này bỏ các abstraction dành cho nhiều loại PII khi chưa có nhu cầu thực tế:

1. Bỏ `PiiMappingCacheRegistry`; inject trực tiếp `AccountMapInMemory`.
2. `SQLAlchemyAccountMapRepository` chỉ truy vấn mapping customer, không nhận model registry hay `mapping_name`.
3. `CustomerIdentityPiiMapping` kế thừa trực tiếp `PiiBase`, dùng tên bảng/cột thật thay cho metadata từ `PiiMappingModelMixin`.
4. Đổi bảng mapping từ `customer_identity_map` thành `account_map`.
5. Snapshot, incremental sync, mapper và reverse lookup đều làm việc trực tiếp với customer cache.

## Phản biện trước khi làm

### 1. Registry chưa tạo giá trị khi chỉ có một cache

`PiiMappingCacheRegistry` buộc mỗi call site phải truyền `mapping_name`, lookup cache và xử lý lỗi cấu hình, trong khi registry chỉ chứa `customer_id`. Chi phí nhận thức và test lớn hơn lợi ích hiện tại. Inject trực tiếp cache customer làm ownership và vòng đời dữ liệu rõ ràng hơn.

### 2. Không nên giữ repository generic bằng metadata model

Repository PII cũ nhận `PII_MAPPING_MODELS`, đọc tên cột qua `__pii_*_attr__` và chọn model bằng chuỗi. Cách này che mất schema thật của query. `SQLAlchemyAccountMapRepository` chỉ phục vụ customer nên truy cập trực tiếp `CustomerIdentityPiiMapping.customer_id`, `.uuid` và `.created_at` sẽ ngắn gọn hơn và dễ kiểm tra hơn.

Nếu có loại PII mới, tạo model, repository, cache, snapshot wiring và dependency riêng. Không mở rộng repository customer bằng một registry mới.

### 3. Rule không cần metadata phân loại PII

Khi chỉ có customer cache, metadata phân loại trong từng rule không còn ảnh hưởng tới runtime. Giữ field này sẽ khiến API gợi ý rằng người dùng có thể chọn cache khác dù hệ thống không hỗ trợ. Vì vậy rule chỉ giữ transformer, còn Dynamic Route khai báo danh sách `pii_columns` cần map.

Hệ quả cần ghi rõ: cho đến khi có wiring riêng, mọi cột PII đều dùng customer cache được inject.

### 4. Đổi tên bảng là thay đổi contract với PII database

`account_map` phải tồn tại trong PII database với các cột `customer_id`, `uuid`, `created_at` trước khi deploy. Project không quản lý bảng PII bằng Alembic của application database, nên deployment cần phối hợp với schema bên ngoài.

## Task breakdown

### Task 1 - Đơn giản hóa model customer

Files:

- `app/pii_models/base.py`
- `app/pii_models/account_map.py`
- `app/pii_models/__init__.py`

Kết quả mong muốn:

- Bỏ `PiiMappingModelMixin` và `PII_MAPPING_MODELS`.
- `CustomerIdentityPiiMapping` kế thừa trực tiếp `PiiBase`.
- Model dùng `__tablename__ = "account_map"` và khai báo trực tiếp các cột customer.

### Task 2 - Chuyển repository thành customer-only

Files:

- `app/repositories/interfaces/pii_mapping.py`
- `app/repositories/sqlalchemy/account_map.py`

Kết quả mong muốn:

- Bỏ tham số `mapping_name` khỏi `get_many` và `get_mappings_batch`.
- Bỏ model registry, model injection và lookup cột động.
- Query trực tiếp model/cột của `CustomerIdentityPiiMapping`.

### Task 3 - Bỏ cache registry khỏi service wiring

Files:

- `app/services/account_map_in_memory.py`
- `app/services/pii_mapping_snapshot.py`
- `app/services/pii_cache_sync.py`
- `app/dependencies/services.py`

Kết quả mong muốn:

- Chỉ còn một `AccountMapInMemory` cho customer.
- Full snapshot và incremental sync đọc thẳng vào cache này.
- Dependency khởi tạo, chia sẻ và đồng bộ trực tiếp cache customer.

### Task 4 - Mapper và query service dùng cache được inject

Files:

- `app/services/query_engine/pii_mapper.py`
- `app/services/query_engine/base_service.py`

Kết quả mong muốn:

- Mapper truyền hashmap `token -> value` của customer cho transformer.
- Reverse lookup dùng hashmap `value -> token` của cùng cache.
- Không còn metadata phân loại hay lookup cache động trong rule.
- Dynamic Route nhận `pii_columns: list[str]` thay cho mapping cột sang loại PII.

### Task 5 - Cập nhật tài liệu và test

Files:

- `README.md`
- `docs/3-flows.md`
- `tests/test_account_map_in_memory.py`
- `tests/test_pii_mapping_repository.py`
- `tests/test_data_query_service.py`

Kết quả mong muốn:

- Tài liệu phản ánh một customer cache và bảng `account_map`.
- Test không còn registry/model registry/mapping name.
- Test repository xác nhận query dùng trực tiếp bảng `account_map`.
- Mapping miss trả `{column_name, value}` với `value` lấy từ row gốc để ghi audit log, trong khi cột response vẫn là `null`.
- Toàn bộ test suite và lint pass.
