# Sprint 1 — PII Cache Refactor

**Ngày tạo:** 2026-07-13  
**Trạng thái:** 📋 Planning

---

## Mục tiêu Sprint

Refactor lại hệ thống PII Mapping Cache để:

1. Đảm bảo snapshot load **xong trước khi app nhận request** — fail hard thay vì degrade silently.
2. Chuyển cấu trúc cache từ flat map sang **dual hashmap** (tra cứu theo cả 2 chiều: `token → value` và `value → token`).
3. Đơn giản hóa layer repository bằng cách gộp 2 iterator thành 1 hàm duy nhất.

---

## Phân tích Codebase hiện tại

### 1. `app/services/pii_mapping_cache.py`

Cache hiện tại lưu:
```python
self._items: dict[_PiiCacheKey, str]  # (pii_type, token) → mapped_value
```

Chỉ tra cứu được **1 chiều** (token → value). Phần `_get_tokens_by_original_values` trong `base_service.py` phải **linear scan toàn bộ cache** để tìm token từ value — O(n) mỗi lần lookup.

### 2. `app/repositories/sqlalchemy/pii_mapping.py`

Có 2 hàm gần như **copy-paste nhau**:
- `iter_snapshot_batches`: keyset-pagination không có `since` filter
- `iter_incremental_batches`: keyset-pagination có thêm điều kiện `created_at > since`

Cả hai đều build `batch: dict[PiiMappingKey, PiiMappingRecord]` bằng cách loop qua `rows` array — hoàn toàn có thể được gộp và đơn giản hóa.

### 3. `app/services/query_engine/pii_mapper.py`

Hàm `map_pii_fields` nhận `pii_cache: dict[PiiMappingKey, str]` (snapshot flat từ `get_all()`) rồi lookup từng row. Hiện trả về `missing_keys` để caller (base_service) xử lý — nhưng theo task mới, bỏ luôn phần mark_missing.

### 4. `app/main.py` — lifespan

Hiện tại khi `initialize_pii_mapping_cache` thất bại sau toàn bộ retries, nó **chỉ log critical và trả về (0, 0)** — app vẫn khởi động bình thường, background sync loop sẽ "recover". Đây là điểm bị task yêu cầu thay đổi: phải **stop app** khi không load được.

---

## Danh sách Task

### Task 1 — Bắt buộc load snapshot trước khi app start, fail hard nếu không load được

**Files ảnh hưởng:**
- `app/dependencies/services.py` — hàm `initialize_pii_mapping_cache`
- `app/main.py` — hàm `lifespan`

**Thay đổi:**

Hiện tại `initialize_pii_mapping_cache` sau khi hết retries thì log critical và **return (0, 0)**:
```python
# Hiện tại — app tiếp tục khởi động dù cache rỗng
logger.critical("pii_cache_init_all_retries_failed ...")
return 0, 0
```

Cần thay bằng raise exception để lifespan bắt được và dừng app:
```python
# Sau refactor — app dừng nếu không load được
logger.critical("pii_cache_init_all_retries_failed ...")
raise RuntimeError("PII mapping cache failed to initialize after all retries") from last_exc
```

Trong `lifespan`, bỏ comment "If init failed (loaded=0)..." vì scenario đó không còn tồn tại.

> **⚠️ Ý kiến phản biện — Task 1:**
>
> **Lý do yêu cầu này hợp lý:**
> Nếu app start mà cache rỗng, mọi PII token sẽ không được map → dữ liệu trả về cho client chứa raw token thay vì giá trị thực — data quality issue nghiêm trọng. Fail-fast rõ ràng hơn là degrade silently.
>
> **Rủi ro cần lưu ý:**
> - Nếu PII Database bị outage tạm thời trong lúc deploy → app không bao giờ start được → downtime hoàn toàn. Thiết kế cũ cho phép app chạy và tự recover khi DB hồi phục.
> - Cần đảm bảo retry config (`pii_sync_init_max_retries`, `pii_sync_init_retry_delay_seconds`) đủ lớn để tránh false-fail.
>
> **Đề xuất:** Giữ yêu cầu fail-hard nhưng giữ lại background sync loop như một "safety net" cho stale data sau khi đã start (2 vấn đề độc lập). App nên exit với code khác 0 để K8s/Docker biết restart.

---

### Task 2 — Dual hashmap trong `InMemoryPiiMappingCache`

**File:** `app/services/pii_mapping_cache.py`

#### Phân tích thiết kế `created_at` per-entry

**Context:** `created_at` cần thiết vì incremental sync dùng watermark `last_synced_at` (= max `created_at` đã load) để query `created_at > last_synced_at`. Hiện tại `pii_mapping_snapshot.py` cập nhật watermark bằng cách loop riêng qua batch:

```python
# Caller phải tự loop 2 lần: 1 lần set_many, 1 lần update watermark
values = {key: record.mapped_value for key, record in batch.items()}
cache.set_many(values)
for record in batch.values():                   # ← loop thứ 2 thừa
    if record.created_at is not None:
        cache.update_last_synced_at(record.created_at)
```

Nếu `set_many` nhận thêm `created_at` per-record → watermark tự cập nhật bên trong cache, caller gọn hơn, không cần loop riêng.

Tuy nhiên, câu hỏi là: `created_at` nên lưu **ở đâu** trong cấu trúc mới?

---

#### So sánh 3 phương án lưu `created_at`

**Phương án A — Lưu `created_at` trong cả 2 entry của dual hashmap**

```python
@dataclass(frozen=True, slots=True)
class _PiiCacheEntry:
    value: str
    created_at: datetime | None

self._by_token: dict[_PiiCacheKey, _PiiCacheEntry]  # token → {mapped_value, created_at}
self._by_value: dict[_PiiCacheKey, _PiiCacheEntry]  # mapped_value → {token, created_at}
```

- ✅ `set_many` nhận `dict[PiiMappingKey, PiiMappingRecord]` và tự cập nhật watermark bên trong
- ✅ Lookup từ value cũng biết `created_at` nếu cần sau này
- ❌ `created_at` lưu **2 lần** cho mỗi record — memory overhead không cần thiết
- ❌ `_by_value` chỉ cần `token`, không cần `created_at` — lưu thừa

**Phương án B — Lưu `created_at` chỉ trong `_by_token`, `_by_value` chỉ lưu string**

```python
@dataclass(frozen=True, slots=True)
class _PiiCacheEntry:
    value: str
    created_at: datetime | None

self._by_token: dict[_PiiCacheKey, _PiiCacheEntry]  # token → {mapped_value, created_at}
self._by_value: dict[_PiiCacheKey, str]             # mapped_value → token (string thôi)
```

- ✅ `_by_token` là map chính — lưu đủ thông tin để update watermark
- ✅ `_by_value` gọn hơn, chỉ là inverted index thuần túy
- ✅ `set_many` vẫn tự update watermark bên trong từ `_by_token`
- ✅ Memory tiết kiệm hơn Phương án A (~50% cho phần created_at)
- ❌ 2 kiểu khác nhau (`_PiiCacheEntry` vs `str`) trong 2 map → code ít đối xứng hơn

**Phương án C — Tách riêng dict `_created_at` độc lập, cả 2 map chỉ lưu string**

```python
self._by_token: dict[_PiiCacheKey, str]      # (pii_type, token) → mapped_value
self._by_value: dict[_PiiCacheKey, str]      # (pii_type, mapped_value) → token
self._created_at: dict[_PiiCacheKey, datetime]  # (pii_type, token) → created_at
```

- ✅ Cả 2 map đối xứng hoàn toàn — cùng kiểu `dict[_PiiCacheKey, str]`
- ✅ Tách bạch rõ ràng: lookup data vs metadata sync
- ✅ `set_many` nhận `created_at`, ghi vào `_created_at`, tự update watermark
- ✅ Memory tương đương B (created_at chỉ lưu 1 lần per record)
- ✅ Dễ bỏ `_created_at` sau này nếu không cần mà không ảnh hưởng 2 map chính
- ❌ 3 dict thay vì 2 → `clear()` phải xóa cả 3

---

#### ✅ Quyết định: Chọn Phương án C

Phương án C là hợp lý nhất vì:
1. **Đối xứng:** cả 2 map chính `_by_token` và `_by_value` đều có kiểu `dict[_PiiCacheKey, str]` — nhất quán, dễ đọc
2. **Single source of truth cho sync:** `_created_at` keyed by `(pii_type, token)` là nguồn duy nhất, không duplicate
3. **Tách biệt concerns:** data lookup tách khỏi sync metadata — nếu sau này không cần per-entry `created_at` nữa, chỉ cần bỏ `_created_at` dict
4. **`set_many` trở thành điểm duy nhất** cập nhật cả 3 dict và watermark — không còn loop thừa ở caller

**Cấu trúc cuối cùng:**

```python
self._by_token: dict[_PiiCacheKey, str]         # (pii_type, token) → mapped_value
self._by_value: dict[_PiiCacheKey, str]         # (pii_type, mapped_value) → token
self._created_at: dict[_PiiCacheKey, datetime]  # (pii_type, token) → created_at
```

**`set_many` mới:**
```python
def set_many(self, records: dict[PiiMappingKey, PiiMappingRecord]) -> None:
    for key, record in records.items():
        cache_key = self._cache_key(key)
        value_key = _PiiCacheKey(pii_type=key.pii_type, token=record.mapped_value)
        self._by_token[cache_key] = record.mapped_value
        self._by_value[value_key] = key.token
        if record.created_at is not None:
            self._created_at[cache_key] = record.created_at
            self._update_last_synced_at(record.created_at)  # private helper
```

> **Lưu ý quan trọng:** `set_many` nhận `dict[PiiMappingKey, PiiMappingRecord]` thay vì `dict[PiiMappingKey, str]` như hiện tại — **signature thay đổi**, cần cập nhật tất cả callers (`pii_mapping_snapshot.py`). Đây là lý do tại sao việc gộp 2 loop (Task 4) và refactor cache (Task 2) phải làm cùng nhau.

**Các hàm cần update:**
- `set_many(records)` → nhận `PiiMappingRecord`, ghi vào cả 3 dict, tự update watermark
- `get_many(keys)` → đọc từ `_by_token` như cũ
- `get_all()` → trả về `dict[PiiMappingKey, str]` từ `_by_token`
- `get_all_by_value()` → **hàm mới**, trả về `dict[PiiMappingKey, str]` từ `_by_value`, thay thế linear scan O(n) trong `base_service._get_tokens_by_original_values`
- `clear()` → xóa cả 3 dict và `_last_synced_at`
- `update_last_synced_at` → chuyển thành private `_update_last_synced_at`, caller bên ngoài không cần gọi nữa
- Bỏ: `mark_missing`, `keys_to_load`, `_missing_until`, `_next_missing_expiry`, `missing_size`, `_clear_expired_missing`

> **⚠️ Ý kiến phản biện — Task 2:**
>
> **Vấn đề 1 — Bỏ negative cache (`mark_missing`)**
> Với thiết kế mới (fail-hard nếu không load snapshot), token thiếu trong cache đồng nghĩa token đó thực sự không có trong DB (đã load hết). Bỏ là hợp lý, nhưng chỉ đúng khi Task 1 là tiền đề bắt buộc.
>
> **Vấn đề 2 — Memory footprint**
> 3 dict thay vì 1, nhưng `_created_at` chỉ lưu `datetime` (8–24 bytes) per record, không đáng kể so với string value. Vẫn cần ước tính tổng số record để confirm.
>
> **Vấn đề 3 — `_by_value` key collision**
> Nếu 2 token khác nhau map về cùng 1 `mapped_value` (ví dụ: UUID trùng do lỗi dữ liệu), entry sau sẽ ghi đè entry trước trong `_by_value`. Reverse lookup sẽ chỉ trả về 1 token. Đây là giới hạn cần document rõ.

---

### Task 3 — Update `PiiMapper` theo cấu trúc hashmap mới, bỏ `mark_missing`

**File:** `app/services/query_engine/pii_mapper.py`

**Thay đổi:**

Bỏ return `missing_keys`, hàm `map_pii_fields` chỉ trả về `list[dict]`:

```python
# Trước
async def map_pii_fields(...) -> tuple[list[dict[str, Any]], set[PiiMappingKey]]:
    return rows, missing_keys

# Sau
async def map_pii_fields(...) -> list[dict[str, Any]]:
    return rows
```

Cập nhật `pii_rules.py` — `PiiValueTransformer` không còn cần trả về `PiiMappingKey | None`:
```python
# Trước
PiiValueTransformer = Callable[[Any, dict[PiiMappingKey, str], str], tuple[Any, PiiMappingKey | None]]

# Sau
PiiValueTransformer = Callable[[Any, dict[PiiMappingKey, str], str], Any]
```

Cập nhật `base_service.py` — bỏ xử lý `missing_keys`.

> **⚠️ Ý kiến phản biện — Task 3:**
>
> **Vấn đề 1 — Bỏ `missing_mappings` trong response**
> `missing_mappings` là signal data quality quan trọng — cho client và operator biết token nào chưa được map. Nếu bỏ, khi có token missing (dữ liệu mới chưa kịp sync vào PII DB), sẽ **không ai biết** tại sao field đó không được map đúng.
>
> **Đề xuất:** Thay vì bỏ hoàn toàn, xem xét giữ lại logic ghi audit log `pii_mapping_missing` ở đâu đó để có thể trace sau. Nếu bỏ khỏi response thì cũng nên bỏ field `missing_mappings` khỏi schema `DataRowsResponse` cho gọn.

---

### Task 4 — Gộp `iter_snapshot_batches` + `iter_incremental_batches` trong repository

**Files ảnh hưởng:**
- `app/repositories/sqlalchemy/pii_mapping.py`
- `app/repositories/interfaces/pii_mapping.py`

**Thay đổi:**

Gộp 2 hàm thành 1 với param `since: datetime | None = None`:

```python
async def iter_batches(
    self,
    *,
    batch_size: int,
    since: datetime | None = None,
) -> AsyncIterator[dict[PiiMappingKey, PiiMappingRecord]]:
    """
    since=None  → full snapshot
    since=dt    → chỉ records có created_at > since
    """
```

**Đơn giản hóa loop — bỏ rows array:**

```python
# Cũ — list rồi loop để build dict
rows = list(result.mappings())
batch: dict = {}
for row in rows:
    key = PiiMappingKey(...)
    batch[key] = PiiMappingRecord(...)
yield batch
last_row = rows[-1]   # dùng lại rows để lấy cursor

# Mới — 1 pass, cursor lấy từ last entry của batch
batch = {}
last_token = None
last_created_at = None
for row in result.mappings():
    token = str(row["token"])
    batch[PiiMappingKey(pii_type=pii_type, token=token)] = PiiMappingRecord(...)
    last_token, last_created_at = token, row["created_at"]
if not batch:
    break
yield batch
cursor_token, cursor_created_at = last_token, last_created_at
```

Cập nhật interface `PiiMappingSnapshotRepository` chỉ còn 1 method.
Cập nhật callers trong `pii_mapping_snapshot.py`.

> **⚠️ Ý kiến phản biện — Task 4:**
>
> **Vấn đề 1 — Bug trong cursor logic của `iter_incremental_batches` hiện tại**
> Vòng đầu tiên filter `created_at > cursor_created_at` (line 149). Từ vòng 2, điều kiện này bị override hoàn toàn bởi keyset condition (lines 153-159) — logic đúng nhưng line 149 bị redundant và gây nhầm lẫn. Khi gộp hàm, cần làm sạch logic này.
>
> **Vấn đề 2 — Phân tầng (Layering concern)**
> Nếu repository trả về `dict[str, _PiiCacheEntry]` thì kiểu `_PiiCacheEntry` (thuộc service layer) sẽ leak xuống repository layer — vi phạm Dependency Inversion. Repository nên giữ return type `dict[PiiMappingKey, PiiMappingRecord]`, việc transform sang dual hashmap là trách nhiệm của service layer (`pii_mapping_snapshot.py`).
>
> **Vấn đề 3 — Cursor tracking per `pii_type`**
> Khi gộp hàm, cần đảm bảo cursor reset đúng cách khi loop sang `pii_type` mới.

---

## Dependency Map giữa các Task

```
Task 1 (Fail-hard startup)
    └── Tiền đề logic của Task 2 (bỏ negative cache)

Task 2 (Dual hashmap cache)
    └── Task 3 (update PiiMapper)

Task 4 (Gộp repository iterator)
    └── Cập nhật callers trong pii_mapping_snapshot.py
    └── Cập nhật interface
```

**Thứ tự implement nên là: Task 4 → Task 2 → Task 3 → Task 1**

Lý do: bắt đầu từ layer thấp nhất (repository) lên trên, tránh compile error giữa chừng khi type signatures thay đổi.

---

## Files sẽ bị ảnh hưởng (Impact Analysis)

| File | Loại thay đổi |
|------|--------------|
| `app/repositories/interfaces/pii_mapping.py` | Sửa Protocol: gộp 2 method → 1 |
| `app/repositories/sqlalchemy/pii_mapping.py` | Gộp 2 hàm iterator, đơn giản hóa loop |
| `app/services/pii_mapping_cache.py` | Dual hashmap, bỏ negative cache logic |
| `app/services/pii_mapping_snapshot.py` | Update caller dùng `iter_batches` |
| `app/services/query_engine/pii_mapper.py` | Bỏ missing_keys, đơn giản hóa return |
| `app/services/query_engine/pii_rules.py` | Update `PiiValueTransformer` type |
| `app/services/query_engine/base_service.py` | Bỏ missing_keys handling, dùng `get_all_by_value` |
| `app/dependencies/services.py` | `initialize_pii_mapping_cache` raise thay vì return (0,0) |
| `app/main.py` | lifespan không cần handle loaded=0 nữa |
| `tests/` | Update tất cả tests liên quan đến cache và repository |

---

## Câu hỏi cần confirm trước khi implement

1. ~~**`created_at` per-entry trong hashmap**~~ ✅ **Đã quyết định:** Dùng Phương án C — tách `_created_at` dict độc lập, `_by_token` và `_by_value` đều lưu `str`. `set_many` nhận `PiiMappingRecord` và tự update watermark bên trong.
2. **`missing_mappings` trong response** — có cần giữ lại để client/monitoring biết có token bị thiếu không, hay bỏ hẳn?
3. **Audit log `pii_mapping_missing`** — khi bỏ `mark_missing`, audit log này có còn được ghi không? Cơ chế ghi từ đâu?
4. **Memory estimate** — số lượng record ước tính trong `customer_identity_map` là bao nhiêu để đánh giá tác động dual hashmap về bộ nhớ?
5. **`_by_value` key collision** — nếu 2 token map về cùng `mapped_value`, reverse lookup chỉ trả 1 kết quả. Đây có phải case thực tế cần xử lý không?
