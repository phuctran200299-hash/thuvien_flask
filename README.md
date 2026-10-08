# Website quản lý thư viện số - Trường Đại học Công nghiệp Việt Trì

Đồ án tốt nghiệp - Trần Đăng Dương - K4658 CNTT

**Công nghệ:** Python 3.12 · Flask 3 · SQL Server 2022 · SQLAlchemy (ORM) · Flask-Migrate · Flask-Login · Flask-WTF ·
Jinja2 · Tailwind CSS · Chart.js · pytest · Playwright

**Tài khoản mẫu:** `admin` / `password123` (quản trị) - `nguyenvana` / `password123` (thành viên)

---

## 1. Cài đặt trên Windows

### Bước 1. Cài phần mềm
1. **Python 3.12**: https://www.python.org/downloads/ (khi cài, tick *Add python.exe to PATH*).
2. **SQL Server 2022 Express**: https://www.microsoft.com/sql-server/sql-server-downloads → chọn *Express* → *Basic*.
3. **SSMS** (SQL Server Management Studio) để xem dữ liệu: https://aka.ms/ssmsfullsetup

### Bước 2. Cấu hình SQL Server cho phép kết nối bằng tài khoản `sa`
SQL Server Express mặc định **chỉ cho đăng nhập Windows và không mở cổng TCP**, cần bật:

1. Mở **SSMS** → kết nối `localhost\SQLEXPRESS` bằng *Windows Authentication*.
2. Chuột phải tên server → *Properties* → *Security* → chọn **SQL Server and Windows Authentication mode** → OK.
3. *Security* → *Logins* → chuột phải **sa** → *Properties*:
   - *General*: đặt mật khẩu mới.
   - *Status*: *Login* = **Enabled** → OK.
4. Mở **SQL Server Configuration Manager** → *SQL Server Network Configuration* → *Protocols for SQLEXPRESS*:
   - Chuột phải **TCP/IP** → *Enable*.
   - Chuột phải **TCP/IP** → *Properties* → tab *IP Addresses* → kéo xuống mục **IPAll**:
     xóa trống *TCP Dynamic Ports*, nhập **TCP Port = 1433** → OK.
5. *SQL Server Services* → chuột phải **SQL Server (SQLEXPRESS)** → *Restart*.

### Bước 3. Cài thư viện Python
Mở *Command Prompt* tại thư mục dự án:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Bước 4. Cấu hình kết nối
Sao chép `.env.example` thành `.env`, sửa `DB_PASS` thành mật khẩu `sa` đã đặt ở bước 2
(mật khẩu có ký tự đặc biệt như `@` vẫn dùng được bình thường).

### Bước 5. Tạo CSDL và chạy

```bat
flask init-db        :: tạo database library_management
flask db upgrade     :: tạo bảng theo migration
flask seed           :: nạp dữ liệu mẫu
flask run            :: chạy web tại http://127.0.0.1:5000
```

> Nạp lại dữ liệu mẫu từ đầu: `flask seed --force`

### Cách khác: chạy bằng Docker (không cần cài SQL Server)

```bash
docker compose up -d --build
```
Mở http://localhost:8000. SQL Server chạy trong container ở cổng 1433 (`sa` / `ThuVien@2026`).

---

## 2. Chức năng

| Tác nhân | Chức năng |
|---|---|
| **Khách vãng lai** | Tra cứu tài liệu theo tên, tác giả, NXB, ISBN, từ khóa, mô tả; lọc theo danh mục, tác giả, NXB, khoảng năm xuất bản, còn bản giấy, có bản số; sắp xếp; xem chi tiết và đánh giá; **đọc tài liệu số công khai**; đăng ký |
| **Thành viên** | Đăng nhập; quản lý thông tin cá nhân, đổi mật khẩu; **đọc trực tuyến và tải tài liệu số theo quyền**; đặt mượn sách giấy, tự hủy phiếu chờ, gia hạn; xem lịch sử mượn trả, tiền phạt, **lịch sử đọc/tải**; đánh giá tài liệu |
| **Quản trị viên / cán bộ thư viện** | Dashboard; **quản lý tài liệu** (thêm/sửa/xóa, ảnh bìa, tải lên nhiều tệp số, đặt quyền đọc/tải); **quản lý danh mục, tác giả, nhà xuất bản**; **quản lý người dùng và phân quyền**; quản lý mượn trả (giao sách, nhận trả, tự tính phạt, hủy phiếu, thu phạt); **theo dõi lịch sử truy cập tài liệu**; **thống kê** (biểu đồ, top tài liệu) và **xuất Excel**, in PDF; cài đặt hệ thống |

### Đối chiếu với đề cương

| Nội dung đề cương | Thực hiện trong hệ thống |
|---|---|
| Python, Flask | `app/` - Flask 3, chia module bằng Blueprint |
| SQL Server, SQLAlchemy, Flask-Migrate | `app/models.py`, thư mục `migrations/` |
| HTML, CSS, JS, Jinja2 | `app/templates/` (giao diện dùng Tailwind CSS) |
| pytest, Playwright | `tests/` (47 test nghiệp vụ), `tests/e2e/` (5 test giao diện) |
| Đăng ký/đăng nhập, quản lý tài khoản | `app/blueprints/auth.py`, `user.py` |
| Tìm kiếm, lọc theo tên, tác giả, danh mục, năm XB, từ khóa | `main.books` |
| Đọc trực tuyến, tải tài liệu, kiểm soát quyền đọc/tải | `main.read`, `main.document`, `services.can_access_document` |
| Quản lý tài liệu, danh mục, tác giả, NXB, tệp tài liệu | `admin.books`, `admin.book_form`, `admin.taxonomy` |
| Quản lý người dùng, phân quyền | `admin.users` |
| Theo dõi lịch sử truy cập tài liệu | bảng `access_logs`, `admin.access_logs` |
| Thống kê tài liệu, người dùng, lượt truy cập | `admin.statistics`, `admin.export` |
| Responsive, đa trình duyệt | Tailwind CSS, kiểm thử bằng Chromium (Playwright) |

---

## 3. Kiến trúc

```mermaid
flowchart TB
    subgraph Client[Trình duyệt]
        UI[Giao diện HTML / Tailwind / Chart.js]
    end
    subgraph Flask[Ứng dụng Flask]
        R[Tầng điều khiển - Blueprints<br/>auth · main · user · admin]
        S[Tầng nghiệp vụ - services.py<br/>mượn trả · phạt · phân quyền · lịch sử]
        M[Tầng dữ liệu - models.py<br/>SQLAlchemy ORM]
    end
    DB[(SQL Server<br/>library_management)]
    FS[/Lưu trữ tài liệu số<br/>storage/documents/]

    UI -- HTTP --> R --> S --> M --> DB
    R -- kiểm tra quyền rồi mới phát tệp --> FS
```

### Cấu trúc thư mục

```
app/
├── __init__.py        create_app: khởi tạo Flask, extension, blueprint, bộ lọc template
├── config.py          cấu hình (đọc từ .env)
├── models.py          11 bảng CSDL
├── services.py        nghiệp vụ: cài đặt, mượn - trả, tiền phạt, quyền tài liệu, lịch sử truy cập, đánh giá
├── utils.py           lưu file upload (kiểm tra chữ ký file), phân trang, định dạng hiển thị
├── cli.py             lệnh flask init-db / seed / expire-pending
├── blueprints/        auth.py · main.py · user.py · admin.py
├── templates/         giao diện Jinja2
└── static/            toast.js, ảnh bìa upload
migrations/            lịch sử thay đổi CSDL (Flask-Migrate / Alembic)
storage/documents/     tệp tài liệu số (không truy cập trực tiếp được qua URL)
tests/                 pytest + Playwright
```

---

## 4. Cơ sở dữ liệu

```mermaid
erDiagram
    categories ||--o{ books : "phân loại"
    authors ||--o{ books : "viết"
    publishers ||--o{ books : "xuất bản"
    books ||--o{ document_files : "có tệp số"
    books ||--o{ borrowing : "được mượn"
    users ||--o{ borrowing : "mượn"
    borrowing ||--o{ borrow_renewals : "gia hạn"
    books ||--o{ book_reviews : "được đánh giá"
    users ||--o{ book_reviews : "viết"
    books ||--o{ access_logs : "được truy cập"
    users |o--o{ access_logs : "truy cập"
    document_files |o--o{ access_logs : "được đọc/tải"

    books {
        int id PK
        nvarchar title
        int author_id FK
        int publisher_id FK
        int category_id FK
        int publish_year
        varchar isbn "UNIQUE khi khác NULL"
        nvarchar keywords
        int quantity
        int available
        varchar access_level "public | member"
        bit allow_download
        int view_count
    }
    document_files {
        int id PK
        int book_id FK
        nvarchar original_name
        varchar stored_name UK
        varchar mime_type
        int file_size
    }
    users {
        int id PK
        varchar username UK
        varchar email UK
        varchar password_hash "pbkdf2:sha256"
        nvarchar full_name
        varchar role "admin | member"
        varchar status "active | inactive | banned"
    }
    borrowing {
        int id PK
        int user_id FK
        int book_id FK
        date borrow_date
        date due_date
        date return_date
        varchar status "pending | borrowing | returned | cancelled"
        int fine_amount
        bit fine_paid
    }
    borrow_renewals {
        int id PK
        int borrow_id FK
        date old_due_date
        date new_due_date
    }
    access_logs {
        bigint id PK
        int user_id FK "NULL = khách"
        int book_id FK
        int file_id FK
        varchar action "view | read | download"
        varchar ip_address
        datetime created_at
    }
    book_reviews {
        int id PK
        int book_id FK
        int user_id FK
        smallint rating "1-5"
        nvarchar comment
    }
    categories {
        int id PK
        nvarchar name UK
    }
    authors {
        int id PK
        nvarchar name UK
    }
    publishers {
        int id PK
        nvarchar name UK
    }
```

Bảng `settings` lưu cấu hình dạng key - value: số ngày mượn, số sách tối đa, số lần và số ngày gia hạn,
số ngày giữ sách, tiền phạt mỗi ngày, thông tin liên hệ.

**Lưu ý thiết kế cho SQL Server**
- Cột chữ dùng `NVARCHAR` (`db.Unicode`) để lưu tiếng Việt; database dùng collation `Vietnamese_CI_AS`.
- `isbn` được phép rỗng nên dùng **chỉ mục UNIQUE có lọc** `WHERE isbn IS NOT NULL`
  (UNIQUE thường của SQL Server chỉ cho phép một giá trị NULL).
- SQL Server không cho nhiều đường xóa dây chuyền tới cùng một bảng, nên `access_logs.file_id` để `NO ACTION`
  và được xử lý trong code khi xóa tệp hoặc tài liệu.

### Quy trình mượn - trả

```mermaid
stateDiagram-v2
    [*] --> pending: Thành viên đặt mượn
    pending --> borrowing: Thủ thư xác nhận giao sách (tính hạn trả từ ngày nhận)
    pending --> cancelled: Hủy hoặc quá số ngày giữ sách
    borrowing --> borrowing: Gia hạn (tối đa N lần, chưa quá hạn)
    borrowing --> returned: Thủ thư nhận trả (tự tính tiền phạt nếu trễ)
    returned --> [*]
    cancelled --> [*]
```

---

## 5. Bảo mật

| Nguy cơ | Biện pháp |
|---|---|
| SQL Injection | Mọi truy vấn qua SQLAlchemy ORM (tham số hóa) |
| XSS | Jinja2 tự escape; thông báo toast hiển thị bằng `textContent` |
| CSRF | Flask-WTF `CSRFProtect` cho mọi form POST, đăng xuất cũng dùng POST |
| Mật khẩu | Băm `pbkdf2:sha256` (Werkzeug), không lưu bản rõ |
| Phiên đăng nhập | Cookie `HttpOnly`, `SameSite=Lax`; làm mới phiên khi đăng nhập; tài khoản bị khóa bị đăng xuất ngay |
| Dò tài khoản | Thông báo đăng nhập sai giống nhau cho mọi trường hợp |
| Open redirect | Tham số `next` chỉ chấp nhận đường dẫn nội bộ |
| Upload | Nhận diện loại file theo chữ ký byte (không tin đuôi file), đổi tên ngẫu nhiên, giới hạn dung lượng |
| Tài liệu số | Lưu ngoài thư mục public, chỉ phát qua route có kiểm tra quyền và ghi lịch sử |
| Mượn đồng thời | Khóa dòng `SELECT ... WITH (UPDLOCK)` (`with_for_update`) trong transaction |
| CSV injection | Ô bắt đầu bằng `= + - @` được thêm dấu `'` khi xuất Excel |

---

## 6. Kiểm thử

```bat
pip install -r requirements-dev.txt
python -m playwright install chromium

pytest              :: 47 test nghiệp vụ (SQLite trong bộ nhớ, ~2 phút)
pytest -m e2e       :: 5 test giao diện bằng trình duyệt Chromium
pytest -m e2e --headed   :: xem trình duyệt tự thao tác
```

Chạy test trên SQL Server thật (tạo trước database `library_test`):

```bat
set TEST_DATABASE_URL=mssql+pymssql://sa:MatKhau@localhost:1433/library_test?charset=utf8
pytest
```

| Nhóm | Nội dung kiểm thử |
|---|---|
| `test_auth.py` | Đăng nhập/đăng ký, tài khoản bị khóa, không lộ tài khoản tồn tại, phân quyền, open redirect, đăng xuất |
| `test_borrowing.py` | Đặt mượn, trùng phiếu, hết sách, giới hạn số sách, nợ phạt, hủy, giao sách, gia hạn, trả trễ tính phạt, tự hủy phiếu quá hạn |
| `test_documents.py` | Quyền đọc/tải, lịch sử truy cập, lượt xem, tìm kiếm, upload và chặn file giả mạo, đánh giá, XSS |
| `test_admin.py` | Quản lý người dùng, danh mục, cài đặt, xuất CSV, CSRF, thống kê |
| `e2e/test_ui.py` | Tra cứu và đọc tài liệu, đặt mượn và thủ thư xác nhận, chống XSS trên giao diện, biểu đồ thống kê |

---

## 7. Tác vụ định kỳ

`flask expire-pending` hủy các phiếu chờ lấy sách quá số ngày giữ. Hệ thống cũng tự chạy việc này khi có người
mở trang mượn trả; lên lịch bằng Windows Task Scheduler nếu muốn chạy hằng ngày:

```
Chương trình:  C:\duong-dan\thuvien_flask\.venv\Scripts\flask.exe
Tham số:       expire-pending
Thư mục:       C:\duong-dan\thuvien_flask
```

## 8. Hạn chế và hướng phát triển
- Chưa gửi email nhắc hạn trả (cần cấu hình SMTP)
- Chưa có hàng chờ đặt trước khi sách hết
- Chưa tìm kiếm toàn văn trong nội dung tệp và chưa có gợi ý tài liệu thông minh
- Xem trực tiếp mới hỗ trợ PDF và TXT; EPUB/DOC/DOCX cần tải về
