"""Cấu hình ứng dụng, đọc từ biến môi trường / file .env."""
import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def _database_url():
    url = os.getenv('DATABASE_URL')
    if url:
        return url
    # Ghép URL SQL Server từ các biến riêng lẻ
    # Mã hóa user/mật khẩu để ký tự đặc biệt như @ : / không làm hỏng URL
    user = quote_plus(os.getenv('DB_USER', 'sa'))
    password = quote_plus(os.getenv('DB_PASS', ''))
    host = os.getenv('DB_HOST', 'localhost')
    port = os.getenv('DB_PORT', '1433')
    name = os.getenv('DB_NAME', 'library_management')
    return f'mssql+pymssql://{user}:{password}@{host}:{port}/{name}?charset=utf8'


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'doi-chuoi-nay-khi-trien-khai')
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}

    UPLOAD_FOLDER = BASE_DIR / 'app' / 'static' / 'uploads'      # ảnh bìa (public)
    DOCUMENT_FOLDER = BASE_DIR / 'storage' / 'documents'          # tài liệu số (không public)
    MAX_CONTENT_LENGTH = 60 * 1024 * 1024
    MAX_IMAGE_SIZE = 5 * 1024 * 1024
    MAX_DOCUMENT_SIZE = 50 * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_TIME_LIMIT = None


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False  # bật lại trong test riêng về CSRF
    # Mặc định test chạy trên SQLite trong bộ nhớ; đặt TEST_DATABASE_URL để test trên SQL Server
    SQLALCHEMY_DATABASE_URI = os.getenv('TEST_DATABASE_URL', 'sqlite://')
    if SQLALCHEMY_DATABASE_URI.startswith('sqlite'):
        from sqlalchemy.pool import StaticPool
        SQLALCHEMY_ENGINE_OPTIONS = {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}
