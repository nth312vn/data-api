# Hướng dẫn tính năng Dynamic API

Tài liệu này hướng dẫn chi tiết quy trình từ lúc **Định nghĩa & Đăng ký (Define & Register)** một Dynamic API mới cho đến lúc **Sử dụng & Thực thi (Use & Execute)** bởi Client, kèm theo cơ chế bảo mật tham số và PII mapping.

---

## Quy trình tổng quan

```mermaid
graph TD
    subgraph Phase 1: Định nghĩa & Đăng ký (Admin)
        A[Admin soạn thảo cấu hình JSON] --> B[Gửi POST /api/v1/dynamic-routes]
        B --> C{Lab Test & SQL Validation}
        C -- Lỗi --> D[Trả về lỗi cấu hình/SQL]
        C -- Thành công --> E[Đăng ký vào Registry bộ nhớ]
    end

    subgraph Phase 2: Sử dụng & Thực thi (Client)
        F[Client gửi GET request] --> G[Chuẩn hoá path & Check Auth]
        G -- Không khớp username --> H[403 Forbidden]
        G -- Hợp lệ --> I[Casting query params sang Python types]
        I --> J[Thực thi Trino với Parameter Binding]
        J --> K[Ánh xạ PII thô thành UUID / Null]
        K --> L[Trả về kết quả JSON cho Client]
    end

    E --> F
```

---

## 1. Giai đoạn 1: Định nghĩa & Đăng ký Dynamic API (Define & Register)

Admin (Quản trị viên) thực hiện định nghĩa và phát hành một API endpoint mới bằng cách gửi yêu cầu:
- **Method:** `POST`
- **Path:** `/api/v1/dynamic-routes`
- **Headers:** `Authorization: Bearer <admin_access_token>`

### 1.1. Cấu trúc một định nghĩa Dynamic Route

Định nghĩa cấu hình JSON nhận vào các thông tin sau:

```json
{
  "path": "power_bi/customer_report",
  "description": "Báo cáo chi tiết khách hàng",
  "sql": "SELECT customer_id, full_name, bank_name FROM hive.default.users WHERE join_date >= :start_date AND bank_name IN :banks",
  "params": {
    "start_date": {
      "type": "date",
      "required": true,
      "description": "Ngày bắt đầu lọc báo cáo"
    },
    "banks": {
      "type": "string_list",
      "required": true,
      "description": "Danh sách ngân hàng cần lọc"
    }
  },
  "pii_rules": {
    "customer_id": {
      "custom_rules": [
        {
          "when_length": 38,
          "token_slice": [5, 37],
          "suffix_slice": [37, null]
        }
      ]
    }
  },
  "lab_test": true,
  "lab_test_params": {
    "start_date": "2026-07-01",
    "banks": "vcb, acb"
  }
}
```

* **`path` (String):** Endpoint URL cho API. Phải bắt đầu bằng namespace tương ứng với user sẽ gọi (ví dụ: `power_bi/customer_report`).
* **`sql` (String):** Câu lệnh SQL template chứa placeholder dạng `:param_name` để gán tham số an toàn.
* **`params` (Object):** Khai báo các tham số SQL, kiểu dữ liệu ép kiểu (`string`, `date`, `integer`, `float`, `boolean`, `string_list`), trạng thái bắt buộc và giá trị mặc định.
* **`pii_rules` (Object):** Khai báo quy tắc giải mã dữ liệu nhạy cảm PII cho từng cột kết quả.
  * **`custom_rules`:** Cho phép định nghĩa quy tắc cắt chuỗi động.
    * `when_length` / `when_min_length`: Điều kiện độ dài chuỗi thô để áp dụng rule.
    * `token_slice`: Toạ độ `[start, end]` để cắt khoá token đem tra cứu cache.
    * `suffix_slice`: Toạ độ `[start, end]` để giữ lại phần hậu tố không mã hoá.
    * `strip_last_as_suffix`: Phím tắt nhanh để lấy ký tự cuối cùng làm hậu tố.

### 1.2. Cơ chế SQL Validation & Lab Test tại thời điểm đăng ký

Khi Admin gửi request đăng ký:
1. **Kiểm tra tham số SQL:** Hệ thống tự động phân tích cú pháp SQL để trích xuất các placeholder `:param_name` và đối chiếu với danh mục `params` khai báo. Nếu không trùng khớp (thiếu hoặc thừa tham số), hệ thống từ chối đăng ký và báo lỗi lập tức.
2. **Chạy thử nghiệm (Lab Test):** Nếu `lab_test: true`, hệ thống ép kiểu các tham số trong `lab_test_params`, thực thi thử câu truy vấn trên Trino, chạy PII mapping và đính kèm kết quả mẫu vào response trả về cho Admin kiểm tra.
3. **Lưu trữ Registry:** Khi các bước trên thành công, cấu hình được nạp vào Registry in-memory của hệ thống và API endpoint bắt đầu sẵn sàng phục vụ.

---

## 2. Giai đoạn 2: Sử dụng & Thực thi API bởi Client (Use & Execute)

Khi API route đã được đăng ký thành công, Client (User thường hoặc các hệ thống báo cáo như Power BI) có thể bắt đầu sử dụng thông qua endpoint:
- **Method:** `GET`
- **Path:** `/api/v1/dynamic-routes/{path:path}`
- **Headers:** `Authorization: Bearer <client_access_token>`

Ví dụ: `GET /api/v1/dynamic-routes/power_bi/customer_report?start_date=2026-07-01&banks=vcb,acb`

### 2.1. Tiếp nhận và Phân quyền tự động (Routing & Auth)
1. **Chuẩn hoá Path:** Middleware loại bỏ prefix `/dynamic-routes` của hệ thống để chuyển đổi đường dẫn yêu cầu về dạng `/power_bi/customer_report`.
2. **Kiểm tra quyền theo Namespace:** Phân đoạn đầu tiên (`power_bi`) được xem là namespace sở hữu API này. Hệ thống kiểm tra:
   - Nếu User có quyền `admin` $\rightarrow$ Cho phép thực thi.
   - Nếu User thường $\rightarrow$ So sánh namespace với `username` của User hiện tại. Nếu khớp (ví dụ: user `power_bi` đang gọi API sở hữu bởi namespace `power_bi`), cho phép thực thi. Ngược lại, trả về lỗi `403 Forbidden`.

### 2.2. Ép kiểu tham số đầu vào (Casting)
Hệ thống duyệt qua cấu hình `params` đã đăng ký:
1. Lấy giá trị của từng tham số từ query parameters của Client.
2. Nếu Client không truyền, hệ thống kiểm tra thuộc tính `required`. Nếu `required=True` $\rightarrow$ báo lỗi thiếu tham số. Nếu không bắt buộc, gán giá trị mặc định `default`.
3. Ép kiểu dữ liệu (Casting) sang kiểu dữ liệu Python tương ứng.

### 2.3. parameterized SQL Execution (Thực thi truy vấn an toàn)
- Câu lệnh SQL template ban đầu và dictionary chứa các tham số đã ép kiểu được truyền vào Trino client.
- SQLAlchemy biên dịch truy vấn và thực hiện **Parameter Binding** ở tầng driver:
  - Giá trị tham số được truyền riêng biệt thay vì nối trực tiếp vào chuỗi SQL thô $\rightarrow$ **Chống SQL Injection**.
  - Các tham số kiểu `string_list` (danh sách) được driver tự động kích hoạt chế độ mở rộng `expanding=True` để biến đổi placeholder dạng `:banks` thành số lượng `?` tương ứng với số lượng phần tử thực tế (ví dụ: `IN (?, ?)`).

### 2.4. Giải mã PII trong bộ nhớ (PII Mapping)
Với kết quả thô nhận về từ Trino, đối với mỗi dòng dữ liệu và mỗi cột có cấu hình `pii_rules`:
1. **Áp dụng Custom Slicing Rules:** Dựa vào độ dài dữ liệu, hệ thống chạy rule khớp và cắt chuỗi thô để lấy `token` và `suffix`.
2. **Lookup Cache:** Tra cứu khoá `token` trong cache in-memory `AccountMapInMemory`:
   - *Nếu tìm thấy:* Giải mã token và ghép với phần `suffix` $\rightarrow$ Trả về kết quả giải mã hoàn chỉnh.
   - *Nếu không tìm thấy (Cache miss):* Ghi nhận thông tin thiếu mapping vào audit log, đồng thời gán giá trị của cột thành `None` (null) để che giấu dữ liệu thô nhạy cảm.

---

## 3. Ví dụ Full Luồng hoạt động từ Đăng ký đến Sử dụng (End-to-End Example)

### 3.1. Trạng thái hệ thống trước khi bắt đầu

#### Dữ liệu trong Database (Trino):
Bảng `hive.default.users` có dữ liệu:
* Dòng 1: `customer_id` = `CUST_12345678901234567890123456789012A`, `full_name` = "Nguyễn Văn A", `bank_name` = "VCB", `join_date` = `2026-07-05`
* Dòng 2: `customer_id` = `CUST_99999999999999999999999999999999B`, `full_name` = "Trần Thị B", `bank_name` = "ACB", `join_date` = `2026-07-10`

#### Dữ liệu giải mã trong Cache bộ nhớ của ứng dụng:
Cache lưu trữ duy nhất cặp key-value:
* Token `12345678901234567890123456789012` $\rightarrow$ UUID thật: `7c37bb4b-0e15-4fb9-b589-f57211ac1679`.
* (Token `99999999999999999999999999999999` chưa được tạo/đồng bộ trong cache giải mã).

---

### 3.2. Bước 1: Admin đăng ký API (Define & Register)

Admin gửi yêu cầu cấu hình API báo cáo khách hàng:
- **POST** `/api/v1/dynamic-routes`
- **Body:**
```json
{
  "path": "power_bi/customer_report",
  "description": "Báo cáo chi tiết khách hàng lọc theo ngân hàng",
  "sql": "SELECT customer_id, full_name, bank_name, join_date FROM hive.default.users WHERE join_date >= :start_date AND bank_name IN :banks",
  "params": {
    "start_date": {
      "type": "date",
      "required": true
    },
    "banks": {
      "type": "string_list",
      "required": true
    }
  },
  "pii_rules": {
    "customer_id": {
      "custom_rules": [
        {
          "when_length": 38,
          "token_slice": [5, 37],
          "suffix_slice": [37, null]
        }
      ]
    }
  }
}
```
*Kết quả:* Hệ thống kiểm tra SQL hợp lệ và đăng ký endpoint này thành công.

---

### 3.3. Bước 2: Client gọi và thực thi API (Use & Execute)

User `power_bi` thực hiện gọi báo cáo của mình:
- **GET** `/api/v1/dynamic-routes/power_bi/customer_report?start_date=2026-07-01&banks=VCB,ACB`

#### backend xử lý chi tiết tại thời điểm chạy:
1. **Auth:** Loại bỏ `/dynamic-routes` prefix $\rightarrow$ path còn lại là `/power_bi/customer_report`. Namespace `power_bi` trùng khớp với username người dùng gọi $\rightarrow$ **Cho phép truy cập**.
2. **Casting:**
   - `start_date` chuyển sang đối tượng `date(2026, 7, 1)`.
   - `banks` chuyển sang danh sách `['VCB', 'ACB']`.
3. **Execute SQL:** Thực thi câu lệnh truy vấn an toàn trên Trino với parameter binding. SQL nhận về 2 dòng dữ liệu thô.
4. **PII Mapping:**
   - **Dòng 1:** Giá trị `CUST_12345678901234567890123456789012A` có chiều dài là 38 $\rightarrow$ cắt lấy token `12345678901234567890123456789012` và suffix `A`. Tra cứu cache thành công $\rightarrow$ Kết quả hiển thị: `7c37bb4b-0e15-4fb9-b589-f57211ac1679A`.
   - **Dòng 2:** Giá trị `CUST_99999999999999999999999999999999B` có chiều dài là 38 $\rightarrow$ cắt lấy token `99999999999999999999999999999999` và suffix `B`. Tra cứu cache thất bại $\rightarrow$ Ghi log missing và trả về kết quả `null` để bảo mật.

---

### 3.4. Bước 3: JSON Response trả về cho Client

Client nhận về dữ liệu an toàn, che giấu các dòng không có ánh xạ giải mã hợp lệ:

```json
{
  "rows": [
    {
      "customer_id": "7c37bb4b-0e15-4fb9-b589-f57211ac1679A",
      "full_name": "Nguyễn Văn A",
      "bank_name": "VCB",
      "join_date": "2026-07-05"
    },
    {
      "customer_id": null,
      "full_name": "Trần Thị B",
      "bank_name": "ACB",
      "join_date": "2026-07-10"
    }
  ],
  "missing_mappings": [
    {
      "column_name": "customer_id",
      "value": "CUST_99999999999999999999999999999999B"
    }
  ]
}
```
