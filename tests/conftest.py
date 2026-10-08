"""Cấu hình chung cho pytest.

Mặc định chạy trên SQLite trong bộ nhớ (nhanh, không cần cài gì thêm).
Chạy trên SQL Server thật:
    set TEST_DATABASE_URL=mssql+pymssql://sa:MatKhau@localhost:1433/library_test?charset=utf8
    pytest
(database library_test phải được tạo trước; mỗi test sẽ xóa và tạo lại toàn bộ bảng)
"""
import pytest

from app import create_app
from app.cli import seed_data
from app.config import TestConfig
from app.extensions import db as _db
from app.models import Book, Borrowing, User


@pytest.fixture()
def app(tmp_path):
    class Config(TestConfig):
        UPLOAD_FOLDER = tmp_path / 'uploads'
        DOCUMENT_FOLDER = tmp_path / 'documents'

    app = create_app(Config)
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        seed_data()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


def _login(client, username, password='password123'):
    return client.post('/login', data={'username': username, 'password': password})


@pytest.fixture()
def member_client(app, record_flashes):
    c = app.test_client()
    _login(c, 'nguyenvana')
    _flashed.clear()  # bỏ thông báo "đăng nhập thành công"
    return c


@pytest.fixture()
def admin_client(app, record_flashes):
    c = app.test_client()
    _login(c, 'admin')
    _flashed.clear()
    return c


@pytest.fixture()
def member(db):
    return User.query.filter_by(username='nguyenvana').one()


@pytest.fixture()
def book_by_title(db):
    def find(title):
        return Book.query.filter(Book.title.like(f'{title}%')).one()
    return find


_flashed = []


@pytest.fixture(autouse=True)
def record_flashes(app):
    """Ghi lại mọi thông báo flash phát ra trong test (kể cả khi trang đã hiển thị chúng)."""
    from flask import message_flashed

    def record(sender, message, category, **extra):
        _flashed.append(message)

    _flashed.clear()
    message_flashed.connect(record, app)
    yield
    message_flashed.disconnect(record, app)


def flashes(client=None):
    """Các thông báo flash phát ra kể từ lần gọi trước (rồi xóa danh sách)."""
    messages = list(_flashed)
    _flashed.clear()
    return messages


def active_borrow(user_id, book_id):
    return Borrowing.query.filter(Borrowing.user_id == user_id, Borrowing.book_id == book_id,
                                  Borrowing.status.in_(('pending', 'borrowing'))).first()
