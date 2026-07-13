# Công nghệ sử dụng (Technology Stack)

Dự án sử dụng một tập hợp các công nghệ hiện đại, mạnh mẽ nhằm đảm bảo hiệu suất cao (high performance), an toàn kiểu dữ liệu (type safety), và tính ổn định khi chạy trên môi trường Production.

## 1. Backend Framework & Ngôn ngữ
- **Python (>= 3.11):** Sử dụng các tính năng mới nhất của Python như Type Hints tĩnh, cải thiện tốc độ và `asyncio` để xử lý I/O không đồng bộ hiệu quả.
- **FastAPI:** Framework web hiện đại, siêu nhanh.
  - Hỗ trợ lập trình bất đồng bộ (`async`/`await`).
  - Validation dữ liệu mạnh mẽ thông qua Pydantic.
  - Tự động sinh tài liệu API (Swagger UI, ReDoc).

## 2. Quản lý Dữ liệu (Database & ORM)
- **PostgreSQL:** Hệ quản trị cơ sở dữ liệu quan hệ chính của ứng dụng, lưu trữ thông tin User, phân quyền và Audit Logs.
- **SQLAlchemy 2.0 (Async):** Công cụ ORM (Object-Relational Mapping) thế hệ mới, hỗ trợ truy vấn bất đồng bộ qua `asyncpg`.
- **Alembic:** Công cụ quản lý schema migration cho SQLAlchemy, giúp theo dõi và cập nhật thay đổi cấu trúc cơ sở dữ liệu một cách an toàn.

## 3. Big Data & Xử lý Dữ liệu (Data Processing)
- **Trino (trước đây là PrestoSQL):** Engine truy vấn SQL phân tán.
  - Dự án kết nối tới Trino thông qua `trino[sqlalchemy]` để truy xuất một khối lượng dữ liệu khổng lồ cho các endpoints cung cấp dữ liệu API.
- **Polars:** Thư viện xử lý dữ liệu viết bằng ngôn ngữ Rust.
  - Vượt trội hơn Pandas về tốc độ và sử dụng bộ nhớ.
  - Được dùng để xử lý và join dữ liệu trong bộ nhớ (in-memory left-joins) cho quá trình đối soát và ánh xạ thông tin cá nhân (PII Mapping).

## 4. Bảo mật & Xác thực (Security & Auth)
- **JWT (JSON Web Tokens):** Quản lý phiên đăng nhập và định danh.
  - Sử dụng cơ chế cặp token: **Access Token** (thời gian sống ngắn, dùng để gọi API) và **Refresh Token** (thời gian sống dài, dùng để cấp lại access token).
- **Bcrypt:** Thuật toán mã hóa một chiều (hashing) để bảo vệ mật khẩu người dùng trước khi lưu vào database.
- **PyJWT:** Thư viện Python để encode và decode JWT an toàn.

## 5. Vận hành & Giám sát (DevOps & Observability)
- **Docker & Docker Compose:** Container hóa ứng dụng, giúp đảm bảo tính đồng nhất giữa các môi trường phát triển (Dev) và sản xuất (Prod).
- **Prometheus Client:** Tích hợp endpoint `/metrics` để theo dõi các chỉ số về performance, lượt requests, errors, v.v., tương thích với hệ sinh thái Prometheus/Grafana.
- **Structured Logging:** Ghi log ở định dạng JSON để dễ dàng thu thập và phân tích trên các hệ thống log tập trung (như ELK, Datadog). Có hỗ trợ log ra file xoay vòng (rotating logs).

## 6. Công cụ phát triển & Code Quality
- **Ruff:** Linter và formatter cực nhanh (viết bằng Rust). Thay thế cho Flake8 và một phần của Black.
- **Black:** Formatter tiêu chuẩn giúp định dạng code thống nhất.
- **Mypy:** Công cụ phân tích và kiểm tra kiểu dữ liệu tĩnh (Static type checker). Ngăn chặn lỗi runtime liên quan đến sai kiểu dữ liệu.
- **Pytest & Pytest-asyncio:** Framework viết unit test và integration test. Hỗ trợ test các hàm `async`.
