"""Lệnh quản trị chạy bằng `flask <lệnh>`:
    flask init-db         Tạo database trên SQL Server (nếu chưa có)
    flask db upgrade      Tạo/cập nhật bảng theo migration (Flask-Migrate)
    flask seed            Nạp dữ liệu mẫu (tài khoản admin/password123)
    flask expire-pending  Hủy phiếu chờ lấy quá hạn (lên lịch chạy hằng ngày)
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import click
from flask import current_app
from sqlalchemy.engine import make_url

from .extensions import db
from .models import (AccessLog, Author, Book, Borrowing, BorrowRenewal, Category, DocumentFile, Publisher, Review,
                     Setting, User)
from .services import DEFAULT_SETTINGS, expire_pending_borrowings


def register(app):
    # Console Windows mặc định không phải UTF-8 -> in tiếng Việt bị lỗi
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    app.cli.add_command(init_db)
    app.cli.add_command(seed)
    app.cli.add_command(expire_pending)


@click.command('init-db')
def init_db():
    """Tạo database trên SQL Server nếu chưa tồn tại."""
    url = make_url(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if not url.drivername.startswith('mssql'):
        click.echo('Không phải SQL Server, bỏ qua bước tạo database.')
        return
    import pymssql
    conn = pymssql.connect(server=url.host, port=str(url.port or 1433), user=url.username,
                           password=url.password, database='master', autocommit=True)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM sys.databases WHERE name = %s', (url.database,))
    if cursor.fetchone():
        click.echo(f'Database "{url.database}" đã tồn tại.')
    else:
        cursor.execute(f'CREATE DATABASE [{url.database}] COLLATE Vietnamese_CI_AS')
        click.echo(f'Đã tạo database "{url.database}".')
    conn.close()


@click.command('expire-pending')
def expire_pending():
    """Hủy các phiếu chờ lấy sách đã quá thời gian giữ sách."""
    count = expire_pending_borrowings()
    click.echo(f'[{datetime.now():%Y-%m-%d %H:%M}] Đã tự động hủy {count} phiếu chờ lấy quá hạn.')


# ================================================
# DỮ LIỆU MẪU
# ================================================
def _make_pdf(path, title, lines):
    """Tạo file PDF tối giản (không cần thư viện ngoài) để demo chức năng đọc."""
    def esc(s):
        return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    content = f'BT /F1 20 Tf 60 780 Td ({esc(title)}) Tj ET\n'
    for i, line in enumerate(lines):
        content += f'BT /F1 12 Tf 60 {740 - i * 20} Td ({esc(line)}) Tj ET\n'
    objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
            f'<< /Length {len(content)} >>\nstream\n{content}endstream',
            '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = b'%PDF-1.4\n', []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n{obj}\nendobj\n'.encode('latin-1')
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode()
    out += b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    path.write_bytes(out)
    return len(out)


@click.command('seed')
@click.option('--force', is_flag=True, help='Xóa toàn bộ dữ liệu cũ trước khi nạp')
def seed(force):
    """Nạp dữ liệu mẫu."""
    if User.query.first() and not force:
        click.echo('Đã có dữ liệu. Dùng --force để xóa và nạp lại.')
        return
    if force:
        for model in (AccessLog, Review, BorrowRenewal, Borrowing, DocumentFile, Book, Author, Publisher, Category, User, Setting):
            db.session.query(model).delete()
        db.session.commit()
    seed_data()
    click.echo('Đã nạp dữ liệu mẫu. Tài khoản: admin / password123, nguyenvana / password123')


def seed_data():
    for key, value, type_, desc in DEFAULT_SETTINGS:
        db.session.add(Setting(key=key, value=value, type=type_, description=desc))

    cats = [Category(name=n, description=d) for n, d in [
        ('Công nghệ thông tin', 'Sách về lập trình, phần mềm, CNTT'),
        ('Kinh tế - Quản lý', 'Sách về kinh tế, quản trị kinh doanh'),
        ('Văn học', 'Sách văn học trong nước và nước ngoài'),
        ('Kỹ năng sống', 'Sách phát triển bản thân, kỹ năng mềm'),
        ('Khoa học - Công nghệ', 'Sách khoa học tự nhiên, công nghệ'),
        ('Tâm lý - Tư duy', 'Sách về tâm lý học, tư duy')]]
    authors = [Author(name=n) for n in ['Nguyễn Văn An', 'Philip Kotler', 'Paulo Coelho', 'Dale Carnegie', 'Yuval Noah Harari']]
    pubs = [Publisher(name=n) for n in ['NXB Giáo dục', 'NXB Trẻ', 'NXB Văn học', 'NXB Tổng hợp', 'NXB Thế giới']]
    db.session.add_all(cats + authors + pubs)

    admin = User(username='admin', full_name='Quản trị viên', email='admin@library.com', phone='0123456789', role='admin')
    member = User(username='nguyenvana', full_name='Nguyễn Văn A', email='nguyenvana@gmail.com', phone='0987654321')
    for u in (admin, member):
        u.set_password('password123')
    db.session.add_all([admin, member])

    img = 'https://images.unsplash.com/photo-{}?w=400&h=600&fit=crop'
    books = [
        Book(title='Lập trình Web với Python và Flask', author=authors[0], publisher=pubs[0], publish_year=2023,
             isbn='978-1234567890', category=cats[0], keywords='python, flask, lập trình web', quantity=12, available=11,
             description='Giáo trình xây dựng ứng dụng web bằng Python và Flask', image=img.format('1543002588-bfa74002ed7e'), access_level='public'),
        Book(title='Marketing 5.0', author=authors[1], publisher=pubs[1], publish_year=2022, isbn='978-1234567891',
             category=cats[1], keywords='marketing, số hóa', quantity=8, available=8,
             description='Marketing thời đại số', image=img.format('1532012197267-da84d127e765')),
        Book(title='Nhà Giả Kim', author=authors[2], publisher=pubs[2], publish_year=2020, isbn='978-1234567892',
             category=cats[2], keywords='tiểu thuyết', quantity=5, available=4, allow_download=False,
             description='Tiểu thuyết nổi tiếng', image=img.format('1497633762265-9d179a990aa6')),
        Book(title='Đắc Nhân Tâm', author=authors[3], publisher=pubs[3], publish_year=2019, isbn='978-1234567893',
             category=cats[3], keywords='giao tiếp, kỹ năng', quantity=0, available=0,
             description='Nghệ thuật giao tiếp', image=img.format('1512820790803-83ca734da794')),
        Book(title='Sapiens: Lược Sử Loài Người', author=authors[4], publisher=pubs[4], publish_year=2021,
             isbn='978-1234567894', category=cats[4], keywords='lịch sử, nhân loại', quantity=15, available=15,
             description='Lịch sử loài người', image=img.format('1544947950-fa07a98d237f'), access_level='public'),
    ]
    db.session.add_all(books)
    db.session.flush()

    folder = Path(current_app.config['DOCUMENT_FOLDER'])
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for book, original, stored, title, lines in [
        (books[0], 'lap-trinh-web.pdf', 'sample_web.pdf', 'Lap trinh Web voi Python va Flask',
         ['Tai lieu mau phuc vu demo chuc nang doc truc tuyen.', 'Chuong 1: Gioi thieu', 'Chuong 2: Co so du lieu']),
        (books[4], 'sapiens-trich-doan.pdf', 'sample_sapiens.pdf', 'Sapiens - Trich doan',
         ['Tai lieu mau phuc vu demo.', 'Phan 1: Cach mang nhan thuc']),
        (books[2], 'nha-gia-kim-trich-doan.pdf', 'sample_nha_gia_kim.pdf', 'Nha Gia Kim - Trich doan',
         ['Tai lieu mau phuc vu demo.', 'Tai lieu nay chi cho phep doc truc tuyen.']),
    ]:
        size = _make_pdf(folder / stored, title, lines)
        files.append(DocumentFile(book=book, original_name=original, stored_name=stored,
                                  mime_type='application/pdf', file_size=size, uploaded_by=admin.id))
    db.session.add_all(files)
    db.session.flush()

    today = date.today()
    db.session.add_all([
        Borrowing(user=member, book=books[0], borrow_date=today - timedelta(5), due_date=today + timedelta(9), status='borrowing'),
        Borrowing(user=member, book=books[2], borrow_date=today - timedelta(20), due_date=today - timedelta(6), status='borrowing'),
        Borrowing(user=member, book=books[1], borrow_date=today - timedelta(60), due_date=today - timedelta(46),
                  return_date=today - timedelta(43), status='returned', fine_amount=15000, fine_paid=True),
        Borrowing(user=member, book=books[4], borrow_date=today - timedelta(95), due_date=today - timedelta(81),
                  return_date=today - timedelta(85), status='returned'),
    ])
    now = datetime.now()
    db.session.add_all([
        AccessLog(user=member, book=books[0], action='view', ip_address='127.0.0.1', created_at=now - timedelta(3)),
        AccessLog(user=member, book=books[0], file=files[0], action='read', ip_address='127.0.0.1', created_at=now - timedelta(3)),
        AccessLog(user=member, book=books[0], file=files[0], action='download', ip_address='127.0.0.1', created_at=now - timedelta(2)),
        AccessLog(book=books[4], action='view', ip_address='127.0.0.1', created_at=now - timedelta(1)),
        AccessLog(book=books[4], file=files[1], action='read', ip_address='127.0.0.1', created_at=now - timedelta(1)),
    ])
    db.session.commit()
