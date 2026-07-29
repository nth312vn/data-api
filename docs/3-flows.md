# Luồng hoạt động chi tiết (Flows)

Tài liệu này mô tả chi tiết các luồng logic quan trọng nhất trong hệ thống.

---

## 1. Luồng Xác thực và Phân quyền (Authentication & Authorization)

Hệ thống sử dụng bảo mật dựa trên Token (JWT) kết hợp với Role-based cơ bản.

### 1.1 Đăng nhập (Login)
1. **Client** gửi request `POST /api/v1/auth/login` kèm `username` và `password`.
2. **Controller (API)** nhận request, schema validate dữ liệu.
3. **AuthService** tra cứu user từ database.
4. **AuthService** sử dụng `bcrypt` kiểm tra hash của password.
5. Nếu hợp lệ, hệ thống tạo ra 2 token:
   - **Access Token:** Ngắn hạn (ví dụ 15 phút), dùng để gửi trong Header `Authorization: Bearer <token>`.
   - **Refresh Token:** Dài hạn (ví dụ 7 ngày), mang claim `typ=refresh` và `jti` duy nhất.
6. Trả về cho client.

### 1.2 Phân quyền API (Authorization)
Quyền của User được quy định ở cột `role` trong bảng `users` (`admin` hoặc `user`).
- **Admin:** Được truy cập toàn bộ APIs.
- **User thường:** Chỉ được phép truy cập các APIs (Data Routes) mà segment đầu tiên của URL khớp chính xác với `username` của họ.
  - Ví dụ: User tên là `power_bi` thì chỉ gọi được `/api/v1/power_bi` và `/api/v1/power_bi/*`. Tránh việc gọi chéo dữ liệu của client khác.

---

## 2. Luồng truy xuất dữ liệu & Ánh xạ PII (Data PII Mapping Flow)

Đây là luồng nghiệp vụ cốt lõi của ứng dụng nhằm đảm bảo dữ liệu PII (Personally Identifiable Information - Thông tin định danh cá nhân) không bị lộ và được ánh xạ (map) động từ một database độc lập vào kết quả truy vấn.

**Thiết kế nguyên tắc:**
- Client không được truyền câu SQL thô. Mọi Trino SQL được define cố định trong cấu hình route của code backend.
- Sử dụng cache in-memory để tối ưu hoá việc đọc PII mapping.

### Chi tiết luồng thực thi:

1. **Client Request:** 
   Client gọi API lấy dữ liệu, ví dụ `GET /api/v1/data/users`. Có thể kèm theo các filters như ngày tháng, limit, hoặc các metadata khác (VD: segmentation).

2. **Khởi tạo SQL & Truy vấn Data Warehouse:** 
   `Service` tương ứng xây dựng câu lệnh Trino SQL dựa trên các filter đầu vào, và thực thi câu lệnh SQL đó trên Data Warehouse (Trino) để lấy dữ liệu gốc. Dữ liệu gốc lúc này chứa các "Token PII" chứ chưa phải là thông tin thực.

3. **Khởi tạo cache PII customer:**
   Lúc app vừa khởi động, hệ thống snapshot bảng `account_map` trong PII Database vào `AccountMapInMemory`. Bộ nhớ này chỉ có hashmap thuần:
   - `token -> mapped_value`
   - `mapped_value -> token`

4. **In-memory Mapping:**
   Service đọc cấu hình mapping PII của route và dùng trực tiếp customer cache được inject. Với mỗi row:
   - Nếu column không tồn tại trong row thì bỏ qua.
   - Nếu `row[column_name] is None` thì giữ nguyên `None`, không map.
   - Nếu value khác `None` thì transformer lookup trong customer cache.

5. **Cache Miss:**
   Nếu transformer không map được token, transformer trả `None`. `PiiMapper` chụp giá trị gốc từ `row[column_name]` vào `missing_mappings`, sau đó set giá trị của column đó thành `null` trong `rows`. Endpoint ghi audit log gồm cả request parameters và `missing_mappings`; raw value không được giữ trong cột dữ liệu trả về.

6. **Fail-fast khi thiếu rule:**
   Nếu mapper được gọi nhưng `QuerySpec` không có PII rules, hệ thống raise exception để phát hiện lỗi cấu hình sớm. Rule chỉ giữ transformer cho từng cột và không chứa metadata chọn loại cache.

7. **Trả kết quả:**
   Trả về JSON kết quả cuối cùng với các trường PII đã map thành giá trị thật khi có mapping, hoặc `null` khi không map được.

---

## 3. Dynamic API: prefix authorization và SQL safety

1. Admin gửi `POST /api/v1/dynamic-routes` với `prefix`, relative `path`,
   SQL dùng placeholder `:name`, typed `params` và tùy chọn `lab_test`.
2. API validate prefix/path và dùng SQLGlot với dialect Trino. Chỉ một
   `SELECT` hoặc `WITH ... SELECT` được phép; DML, DDL, command, multi-statement
   và control/format characters bị từ chối trước khi gọi Trino.
3. AST được render thành canonical SQL, parse/validate lại, đối chiếu chính xác
   với parameter definitions rồi lưu vào PostgreSQL `dynamic_routes`.
4. Runtime request tới `GET /api/v1/{prefix}/{path:path}` chạy
   `require_api_permission()` trước repository lookup. User thường chỉ được
   dùng prefix trùng chính xác username.
5. Service đọc canonical SQL từ database, revalidate, cast query values theo
   type và gửi statement cùng mapping bind riêng tới Trino. Payload
   `APAC' OR 1=1 --` vẫn là một string value.
6. Response Dynamic API không gọi PII mapper và luôn trả
   `missing_mappings: []`. Audit chỉ lưu metadata route an toàn, không lưu SQL
   hoặc bound values.

Management và runtime là hai nhóm route độc lập:

```text
Management: /api/v1/dynamic-routes
Runtime:    /api/v1/{prefix}/{path:path}
```
