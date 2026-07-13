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

3. **In-memory Mapping (Cache Hit):** 
   Dữ liệu gốc được tải vào Dataframe bằng **Polars**. Service đọc cấu hình mapping PII của route đó và tiến hành left-join dữ liệu với In-memory PII Cache.
   *(Lưu ý: Lúc app vừa khởi động, một tiến trình đã fetch trước các bản ghi mapping phổ biến từ PII Database vào Cache bằng keyset-pagination để tối ưu.)*

4. **Cache Miss & Load từ PII Database:** 
   Nếu quá trình join phát hiện có các PII Token bị thiếu (không có trong Cache):
   - Service sẽ nhặt các Token thiếu đó ra.
   - Gửi truy vấn batch (có giới hạn số lượng) tới **PII Database độc lập** để lấy giá trị thực của các Token này.
   - Các bản ghi lấy được sẽ được thêm mới vào In-memory Cache, chia sẻ chung để các request sau (từ bất kỳ hệ thống nào) cũng dùng được.

5. **Negative Caching:**
   Trường hợp query PII Database mà vẫn không tìm thấy Token đó (có thể do lỗi dữ liệu hoặc chưa sync kịp), hệ thống sẽ lưu token đó vào **Negative Cache** (Cache rỗng) với một khoảng thời gian sống nhất định (TTL). Điều này giúp hệ thống không bị spam query liên tục xuống PII Database với những Token lỗi.

6. **Ghi Log (Audit):**
   Với những Token thực sự không tìm thấy trong DB, Service sẽ tiến hành ghi log lưu vào bảng `audit_logs` của cơ sở dữ liệu chính với `event_type=pii_mapping_missing` để phục vụ tra soát.

7. **Trả kết quả:**
   Hoàn tất quá trình Polars DataFrame Left-Join, trả về cục JSON kết quả cuối cùng đã được bổ sung thông tin ánh xạ cho Client.
