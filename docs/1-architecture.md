# Kiến trúc Dự án (Project Architecture)

Dự án này là một API Backend được xây dựng hướng tới tiêu chuẩn Production, sử dụng kiến trúc phân tầng (Layered Architecture). Mục tiêu của kiến trúc này là giữ cho mã nguồn có tính module hóa cao, dễ dàng bảo trì và mở rộng trong tương lai.

## Tổng quan các tầng (Layers)

Kiến trúc được chia thành các module với trách nhiệm rõ ràng (Separation of Concerns). Toàn bộ mã nguồn chính nằm trong thư mục `app/`:

- `app/api/`: **Tầng Routing (Controllers)**
  - Chỉ chứa các định nghĩa HTTP routes (endpoints).
  - Nhiệm vụ: Xác thực hình dáng request/response đầu vào và đầu ra, gọi đến các Services tương ứng. Không chứa logic nghiệp vụ.

- `app/services/`: **Tầng Nghiệp vụ (Business Logic)**
  - Trái tim của ứng dụng. Xử lý các luồng nghiệp vụ phức tạp, quyết định khi nào cần sử dụng database transaction.
  - Ví dụ: Logic đăng nhập, đăng ký, cập nhật thông tin cá nhân, xử lý dữ liệu và mapping PII.

- `app/repositories/`: **Tầng Tương tác Dữ liệu (Data Access Layer)**
  - Định nghĩa các interface và class triển khai việc truy xuất dữ liệu từ Database (sử dụng SQLAlchemy).
  - Tầng `services` chỉ phụ thuộc vào `repositories`, không trực tiếp gọi ORM (SQLAlchemy session), giúp dễ dàng mock khi viết unit test.

- `app/infrastructure/`: **Tầng Cơ sở hạ tầng**
  - Quản lý các kết nối đến hệ thống bên ngoài (Ví dụ: Database Sessions, Unit of Work, Redis kết nối nếu có).
  - Quản lý vòng đời của database session để truyền cho repositories/services sử dụng.

- `app/models/` & `app/pii_models/`: **Tầng Entity (ORM Models)**
  - Chứa các định nghĩa bảng trong cơ sở dữ liệu (SQLAlchemy Declarative Models).
  - `models/` dành cho main database (chứa users, logs,...).
  - `pii_models/` dành cho cơ sở dữ liệu chứa PII Mapping độc lập.

- `app/schemas/`: **Tầng Data Transfer Objects (DTOs)**
  - Định nghĩa các Pydantic models.
  - Dùng để validate dữ liệu đầu vào (request body/query) và serialize dữ liệu đầu ra (response).

- `app/core/`: **Tầng Core & Cấu hình**
  - Chứa các thiết lập và tiện ích dùng chung cho toàn bộ app.
  - Bao gồm: Đọc biến môi trường (Config), xử lý bảo mật, cấu hình Logging, và xử lý Exception toàn cục (Global Exception Handlers).

- `app/dependencies/`: **Tầng Phụ thuộc (Dependency Injection)**
  - Nơi cài đặt các FastAPI dependencies (ví dụ: lấy current user, lấy database session, v.v.).
  - Giúp loại bỏ logic khởi tạo đối tượng phức tạp ra khỏi route handler và services.

## Khả năng Mở rộng (Scalability & Extensibility)

Với cấu trúc trên, khi cần thêm một tính năng mới (Ví dụ: `Product`, `Order`), chúng ta chỉ cần tạo thêm các thành phần tương ứng:
- `ProductModel` trong `models`
- `ProductSchema` trong `schemas`
- `ProductRepository` trong `repositories`
- `ProductService` trong `services`
- `ProductRouter` trong `api`

Điều này đảm bảo mã nguồn mới không làm ảnh hưởng đến các tầng hiện tại và không phá vỡ logic của những tính năng khác.
