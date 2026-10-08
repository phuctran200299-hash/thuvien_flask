"""Mô hình dữ liệu (SQLAlchemy ORM).

Chú ý cho SQL Server:
- Dùng Unicode/UnicodeText (NVARCHAR) để lưu tiếng Việt.
- ISBN được phép rỗng nên dùng chỉ mục UNIQUE có lọc (WHERE isbn IS NOT NULL),
  vì UNIQUE thường của SQL Server chỉ cho phép một giá trị NULL.
- SQL Server không cho phép nhiều đường xóa dây chuyền (cascade) tới cùng một bảng,
  nên access_logs.file_id để NO ACTION và được xử lý trong code khi xóa tệp/sách.
"""
from datetime import date, datetime

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def now():
    return datetime.now()


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    updated_at = db.Column(db.DateTime, nullable=False, default=now, onupdate=now)


class Category(TimestampMixin, db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode(100), nullable=False, unique=True)
    description = db.Column(db.UnicodeText)
    books = db.relationship('Book', back_populates='category', passive_deletes=True)


class Author(TimestampMixin, db.Model):
    __tablename__ = 'authors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode(150), nullable=False, unique=True)
    description = db.Column(db.UnicodeText)
    books = db.relationship('Book', back_populates='author', passive_deletes=True)


class Publisher(TimestampMixin, db.Model):
    __tablename__ = 'publishers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode(150), nullable=False, unique=True)
    description = db.Column(db.UnicodeText)
    books = db.relationship('Book', back_populates='publisher', passive_deletes=True)


class Book(TimestampMixin, db.Model):
    """Tài liệu: có thể có bản giấy (quantity/available) và/hoặc tệp số (files)."""
    __tablename__ = 'books'
    __table_args__ = (
        Index('uq_books_isbn', 'isbn', unique=True,
              mssql_where=db.text('isbn IS NOT NULL'), sqlite_where=db.text('isbn IS NOT NULL')),
        CheckConstraint('available >= 0 AND available <= quantity', name='ck_books_available'),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Unicode(200), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('authors.id', ondelete='SET NULL'), index=True)
    publisher_id = db.Column(db.Integer, db.ForeignKey('publishers.id', ondelete='SET NULL'), index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id', ondelete='SET NULL'), index=True)
    publish_year = db.Column(db.Integer, index=True)
    isbn = db.Column(db.String(20))
    keywords = db.Column(db.Unicode(255))
    description = db.Column(db.UnicodeText)
    image = db.Column(db.Unicode(500))
    quantity = db.Column(db.Integer, nullable=False, default=0)
    available = db.Column(db.Integer, nullable=False, default=0)
    # public: ai cũng đọc được bản số; member: phải đăng nhập
    access_level = db.Column(db.String(10), nullable=False, default='member')
    allow_download = db.Column(db.Boolean, nullable=False, default=True)
    view_count = db.Column(db.Integer, nullable=False, default=0)

    author = db.relationship('Author', back_populates='books')
    publisher = db.relationship('Publisher', back_populates='books')
    category = db.relationship('Category', back_populates='books')
    files = db.relationship('DocumentFile', back_populates='book', cascade='all, delete-orphan',
                            order_by='DocumentFile.created_at')
    reviews = db.relationship('Review', back_populates='book', cascade='all, delete-orphan',
                              order_by='Review.created_at.desc()')

    @property
    def author_name(self):
        return self.author.name if self.author else None

    @property
    def publisher_name(self):
        return self.publisher.name if self.publisher else None


class DocumentFile(db.Model):
    """Tệp tài liệu số; lưu trong storage/documents, chỉ phát qua route có kiểm tra quyền."""
    __tablename__ = 'document_files'
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), nullable=False, index=True)
    original_name = db.Column(db.Unicode(255), nullable=False)
    stored_name = db.Column(db.String(100), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    book = db.relationship('Book', back_populates='files')

    @property
    def extension(self):
        return self.stored_name.rsplit('.', 1)[-1].upper()

    @property
    def previewable(self):
        return self.mime_type in ('application/pdf', 'text/plain')


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.Unicode(100), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    phone = db.Column(db.String(20))
    address = db.Column(db.UnicodeText)
    role = db.Column(db.String(10), nullable=False, default='member')       # admin | member
    status = db.Column(db.String(10), nullable=False, default='active')     # active | inactive | banned

    borrowings = db.relationship('Borrowing', back_populates='user', passive_deletes=True)

    ROLES = ('admin', 'member')
    STATUSES = ('active', 'inactive', 'banned')

    def set_password(self, password):
        # pbkdf2:sha256 (600.000 vòng lặp): ổn định trên Windows; scrypt đôi khi lỗi cấp phát bộ nhớ OpenSSL
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_active(self):  # Flask-Login: tài khoản bị khóa/tạm ngưng sẽ bị đăng xuất
        return self.status == 'active'

    @property
    def initials(self):
        parts = self.full_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.full_name[:2].upper()


class Borrowing(TimestampMixin, db.Model):
    """Phiếu mượn sách giấy.
    pending (chờ lấy) -> borrowing (đang mượn) -> returned (đã trả)
    pending -> cancelled (hủy hoặc quá hạn giữ sách)
    Quá hạn = borrowing và due_date < hôm nay (tính động).
    """
    __tablename__ = 'borrowing'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), nullable=False, index=True)
    borrow_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date)
    status = db.Column(db.String(10), nullable=False, default='pending', index=True)
    fine_amount = db.Column(db.Integer, nullable=False, default=0)
    fine_paid = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.UnicodeText)

    user = db.relationship('User', back_populates='borrowings')
    book = db.relationship('Book')
    renewals = db.relationship('BorrowRenewal', back_populates='borrowing', cascade='all, delete-orphan')

    STATUS_LABELS = {'pending': 'Chờ lấy sách', 'borrowing': 'Đang mượn',
                     'returned': 'Đã trả', 'cancelled': 'Đã hủy'}

    @property
    def is_overdue(self):
        return self.status == 'borrowing' and self.due_date < date.today()

    @property
    def overdue_days(self):
        return (date.today() - self.due_date).days if self.is_overdue else 0

    @property
    def days_remaining(self):
        return (self.due_date - date.today()).days

    @property
    def renew_count(self):
        return len(self.renewals)

    @property
    def status_label(self):
        if self.is_overdue:
            return f'Quá hạn {self.overdue_days} ngày'
        return self.STATUS_LABELS.get(self.status, self.status)


class BorrowRenewal(db.Model):
    __tablename__ = 'borrow_renewals'
    id = db.Column(db.Integer, primary_key=True)
    borrow_id = db.Column(db.Integer, db.ForeignKey('borrowing.id', ondelete='CASCADE'), nullable=False, index=True)
    old_due_date = db.Column(db.Date, nullable=False)
    new_due_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    borrowing = db.relationship('Borrowing', back_populates='renewals')


class Review(TimestampMixin, db.Model):
    __tablename__ = 'book_reviews'
    __table_args__ = (
        UniqueConstraint('book_id', 'user_id', name='uq_review_book_user'),
        CheckConstraint('rating BETWEEN 1 AND 5', name='ck_review_rating'),
    )
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.SmallInteger, nullable=False)
    comment = db.Column(db.UnicodeText)

    book = db.relationship('Book', back_populates='reviews')
    user = db.relationship('User')


class AccessLog(db.Model):
    """Lịch sử truy cập tài liệu: view (xem thông tin), read (đọc trực tuyến), download (tải về)."""
    __tablename__ = 'access_logs'
    id = db.Column(db.BigInteger().with_variant(db.Integer, 'sqlite'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), index=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), nullable=False, index=True)
    file_id = db.Column(db.Integer, db.ForeignKey('document_files.id'))  # NO ACTION (xem ghi chú đầu file)
    action = db.Column(db.String(10), nullable=False, index=True)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Unicode(255))
    created_at = db.Column(db.DateTime, nullable=False, default=now, index=True)

    user = db.relationship('User')
    book = db.relationship('Book')
    file = db.relationship('DocumentFile')

    ACTION_LABELS = {'view': 'Xem thông tin', 'read': 'Đọc trực tuyến', 'download': 'Tải về'}


class Setting(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    value = db.Column(db.UnicodeText)
    type = db.Column(db.String(20), nullable=False, default='text')  # text|textarea|number|email|url
    description = db.Column(db.Unicode(255))


class Reservation(TimestampMixin, db.Model):
    """Đặt trước sách đang hết: xếp hàng chờ, khi có sách trả về hệ thống tự tạo phiếu chờ lấy cho người đầu hàng.
    waiting (đang chờ) -> fulfilled (đã chuyển thành phiếu mượn) | cancelled (người dùng hủy)
    """
    __tablename__ = 'reservations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default='waiting', index=True)

    user = db.relationship('User')
    book = db.relationship('Book')

    STATUS_LABELS = {'waiting': 'Đang chờ', 'fulfilled': 'Đã có sách', 'cancelled': 'Đã hủy'}


class Notification(db.Model):
    """Thông báo trong hệ thống gửi tới người dùng."""
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    message = db.Column(db.Unicode(500), nullable=False)
    link = db.Column(db.String(255))
    # Khóa chống gửi trùng (vd. nhắc hạn trả của cùng một phiếu trong cùng một ngày)
    dedup_key = db.Column(db.String(100), index=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now, index=True)


class Favorite(db.Model):
    """Tủ sách yêu thích của thành viên."""
    __tablename__ = 'favorites'
    __table_args__ = (UniqueConstraint('user_id', 'book_id', name='uq_favorite_user_book'),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now)

    book = db.relationship('Book')
