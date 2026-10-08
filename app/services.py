"""Tầng nghiệp vụ: cài đặt hệ thống, mượn - trả, tiền phạt, phân quyền tài liệu số, lịch sử truy cập.

Các hàm thay đổi dữ liệu tự commit khi thành công và rollback khi lỗi.
Lỗi nghiệp vụ (hiển thị được cho người dùng) được ném ra dưới dạng BusinessError.
"""
import re
from datetime import date, datetime, timedelta

from flask import request
from flask_login import current_user
from sqlalchemy import func, select

from .extensions import db
from .models import AccessLog, Book, Borrowing, BorrowRenewal, Review, Setting


class BusinessError(Exception):
    """Lỗi nghiệp vụ, thông điệp an toàn để hiển thị cho người dùng."""


# ================================================
# CÀI ĐẶT HỆ THỐNG
# ================================================
DEFAULT_SETTINGS = [
    # key, value, type, mô tả
    ('site_name', 'Thư viện số ĐHCN Việt Trì', 'text', 'Tên website'),
    ('site_description', 'Website quản lý thư viện số Trường Đại học Công nghiệp Việt Trì', 'textarea', 'Mô tả website'),
    ('contact_email', 'library@example.com', 'email', 'Email liên hệ'),
    ('contact_phone', '0210-1234-567', 'text', 'Số điện thoại liên hệ'),
    ('contact_address', 'Việt Trì, Phú Thọ', 'textarea', 'Địa chỉ thư viện'),
    ('opening_hours', 'Thứ 2 - Thứ 6: 7:30 - 17:00, Thứ 7: 7:30 - 11:30', 'textarea', 'Giờ mở cửa'),
    ('max_borrow_days', '14', 'number', 'Số ngày mượn tối đa'),
    ('max_books_per_user', '5', 'number', 'Số sách tối đa mỗi người mượn cùng lúc (tính cả phiếu chờ lấy)'),
    ('max_renewals', '2', 'number', 'Số lần gia hạn tối đa mỗi phiếu'),
    ('renew_days', '7', 'number', 'Số ngày cộng thêm mỗi lần gia hạn'),
    ('pending_expire_days', '3', 'number', 'Số ngày giữ sách cho phiếu chờ lấy trước khi tự hủy'),
    ('fine_per_day', '5000', 'number', 'Tiền phạt mỗi ngày trả trễ (VNĐ)'),
]


def all_settings():
    return {s.key: s for s in Setting.query.order_by(Setting.id).all()}


def get_setting(key, default=''):
    setting = db.session.execute(select(Setting).filter_by(key=key)).scalar_one_or_none()
    return setting.value if setting and setting.value is not None else default


def get_setting_int(key, default):
    try:
        value = int(get_setting(key, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def update_settings(form):
    """Cập nhật các setting có trong CSDL; kiểm tra theo kiểu dữ liệu. Trả về danh sách lỗi."""
    errors = []
    settings = all_settings()
    for key, setting in settings.items():
        if key not in form:
            continue
        value = form.get(key, '').strip()
        label = setting.description or key
        if setting.type == 'number' and not value.isdigit():
            errors.append(f'{label} phải là số nguyên không âm')
        elif setting.type == 'email' and value and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value):
            errors.append(f'{label} không hợp lệ')
        elif setting.type == 'url' and value and not re.match(r'https?://', value):
            errors.append(f'{label} phải bắt đầu bằng http:// hoặc https://')
        setting.value = value
    if errors:
        db.session.rollback()
    else:
        db.session.commit()
    return errors


# ================================================
# MƯỢN - TRẢ
# ================================================
def calculate_fine(due_date, return_date=None):
    late_days = ((return_date or date.today()) - due_date).days
    return late_days * get_setting_int('fine_per_day', 5000) if late_days > 0 else 0


def count_active_borrows(user_id):
    return db.session.scalar(
        select(func.count(Borrowing.id)).where(Borrowing.user_id == user_id,
                                               Borrowing.status.in_(('pending', 'borrowing'))))


def unpaid_fine(user_id):
    return db.session.scalar(
        select(func.coalesce(func.sum(Borrowing.fine_amount), 0))
        .where(Borrowing.user_id == user_id, Borrowing.fine_amount > 0, Borrowing.fine_paid == db.false())) or 0


def _lock_book(book_id):
    # SELECT ... WITH (UPDLOCK, ROWLOCK) trên SQL Server: chặn 2 người cùng mượn cuốn cuối cùng
    return db.session.execute(select(Book).where(Book.id == book_id).with_for_update()).scalar_one_or_none()


def _lock_borrowing(borrow_id, **filters):
    stmt = select(Borrowing).where(Borrowing.id == borrow_id).filter_by(**filters).with_for_update()
    return db.session.execute(stmt).scalar_one_or_none()


def _run(fn):
    """Chạy fn trong transaction; commit nếu thành công, rollback nếu có lỗi."""
    try:
        result = fn()
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


def expire_pending_borrowings():
    """Tự hủy các phiếu chờ lấy sách quá số ngày giữ, trả lại số lượng sách. Trả về số phiếu đã hủy."""
    deadline = datetime.now() - timedelta(days=get_setting_int('pending_expire_days', 3))
    expired = Borrowing.query.filter(Borrowing.status == 'pending', Borrowing.created_at < deadline).all()

    def work():
        for borrowing in expired:
            borrowing.status = 'cancelled'
            borrowing.notes = 'Tự động hủy do quá hạn lấy sách'
            book = _lock_book(borrowing.book_id)
            if book:
                book.available = min(book.quantity, book.available + 1)
        return len(expired)

    return _run(work) if expired else 0


def borrow_book(user, book_id):
    """Thành viên đặt mượn sách giấy -> tạo phiếu 'pending'."""
    expire_pending_borrowings()
    max_books = get_setting_int('max_books_per_user', 5)
    borrow_days = get_setting_int('max_borrow_days', 14)

    debt = unpaid_fine(user.id)
    if debt > 0:
        raise BusinessError(f'Bạn còn khoản phạt chưa thanh toán ({debt:,.0f}đ). '
                            'Vui lòng thanh toán tại thư viện trước khi mượn tiếp.'.replace(',', '.'))

    def work():
        book = _lock_book(book_id)
        if not book or book.available <= 0:
            raise BusinessError('Sách không còn sẵn để mượn')
        exists = db.session.scalar(select(func.count(Borrowing.id)).where(
            Borrowing.user_id == user.id, Borrowing.book_id == book_id,
            Borrowing.status.in_(('pending', 'borrowing'))))
        if exists:
            raise BusinessError('Bạn đã đặt hoặc đang mượn sách này rồi')
        if count_active_borrows(user.id) >= max_books:
            raise BusinessError(f'Bạn chỉ được mượn tối đa {max_books} cuốn cùng lúc (tính cả phiếu đang chờ lấy)')

        # Ngày mượn/hạn trả tạm tính; được tính lại khi thủ thư xác nhận giao sách
        borrowing = Borrowing(user_id=user.id, book_id=book_id, borrow_date=date.today(),
                              due_date=date.today() + timedelta(days=borrow_days), status='pending')
        book.available -= 1
        db.session.add(borrowing)
        db.session.flush()
        return borrowing

    return _run(work)


def cancel_by_user(user, borrow_id):
    def work():
        borrowing = _lock_borrowing(borrow_id, user_id=user.id, status='pending')
        if not borrowing:
            raise BusinessError('Không tìm thấy phiếu đặt mượn đang chờ')
        borrowing.status = 'cancelled'
        borrowing.notes = 'Người dùng tự hủy'
        book = _lock_book(borrowing.book_id)
        book.available = min(book.quantity, book.available + 1)

    _run(work)


def renew_borrowing(user, borrow_id):
    max_renewals = get_setting_int('max_renewals', 2)
    renew_days = get_setting_int('renew_days', 7)

    def work():
        borrowing = _lock_borrowing(borrow_id, user_id=user.id, status='borrowing')
        if not borrowing:
            raise BusinessError('Không tìm thấy thông tin mượn sách hoặc sách chưa được lấy')
        if borrowing.renew_count >= max_renewals:
            raise BusinessError(f'Bạn đã gia hạn tối đa {max_renewals} lần cho sách này')
        if borrowing.due_date < date.today():
            raise BusinessError('Không thể gia hạn sách đã quá hạn. Vui lòng trả sách và liên hệ thư viện.')
        old_due = borrowing.due_date
        borrowing.due_date = old_due + timedelta(days=renew_days)
        db.session.add(BorrowRenewal(borrowing=borrowing, old_due_date=old_due, new_due_date=borrowing.due_date))
        return borrowing

    borrowing = _run(work)
    return borrowing, borrowing.renew_count, max_renewals


def admin_update_borrowing(borrow_id, action):
    """Thủ thư xử lý phiếu: confirm_pickup | confirm_return | cancel | mark_paid. Trả về thông báo."""
    def work():
        borrowing = _lock_borrowing(borrow_id)
        if not borrowing:
            raise BusinessError('Không tìm thấy phiếu mượn')

        if action == 'confirm_pickup':
            if borrowing.status != 'pending':
                raise BusinessError('Phiếu không ở trạng thái chờ lấy sách')
            borrowing.status = 'borrowing'
            borrowing.borrow_date = date.today()
            borrowing.due_date = date.today() + timedelta(days=get_setting_int('max_borrow_days', 14))
            return 'Đã xác nhận người dùng lấy sách'

        if action == 'confirm_return':
            if borrowing.status != 'borrowing':
                raise BusinessError('Phiếu không ở trạng thái đang mượn')
            fine = calculate_fine(borrowing.due_date)
            borrowing.status = 'returned'
            borrowing.return_date = date.today()
            borrowing.fine_amount = fine
            borrowing.fine_paid = fine == 0
            book = _lock_book(borrowing.book_id)
            book.available = min(book.quantity, book.available + 1)
            return (f'Đã nhận lại sách. Trả trễ, tiền phạt: {fine:,}đ'.replace(',', '.')
                    if fine else 'Đã nhận lại sách đúng hạn')

        if action == 'cancel':
            if borrowing.status != 'pending':
                raise BusinessError('Chỉ hủy được phiếu đang chờ lấy sách')
            borrowing.status = 'cancelled'
            borrowing.notes = 'Thủ thư hủy phiếu'
            book = _lock_book(borrowing.book_id)
            book.available = min(book.quantity, book.available + 1)
            return 'Đã hủy phiếu mượn'

        if action == 'mark_paid':
            if borrowing.fine_amount <= 0 or borrowing.fine_paid:
                raise BusinessError('Phiếu này không có khoản phạt cần thu')
            borrowing.fine_paid = True
            return f'Đã ghi nhận thanh toán tiền phạt {borrowing.fine_amount:,}đ'.replace(',', '.')

        raise BusinessError('Hành động không hợp lệ')

    return _run(work)


# ================================================
# TÀI LIỆU SỐ: PHÂN QUYỀN, LỊCH SỬ TRUY CẬP, ĐÁNH GIÁ
# ================================================
def can_access_document(book, action='read', user=None):
    """Trả về (được phép, lý do). action: read | download."""
    user = user if user is not None else current_user
    logged_in = bool(user and user.is_authenticated)
    if book.access_level == 'member' and not logged_in:
        return False, 'Tài liệu này chỉ dành cho thành viên. Vui lòng đăng nhập.'
    if action == 'download' and not book.allow_download and not (logged_in and user.is_admin):
        return False, 'Tài liệu này chỉ cho phép đọc trực tuyến, không cho phép tải về.'
    return True, ''


def log_access(book_id, action, file_id=None):
    db.session.add(AccessLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        book_id=book_id, file_id=file_id, action=action,
        ip_address=(request.remote_addr or '')[:45],
        user_agent=(request.user_agent.string or '')[:255],
    ))
    db.session.commit()


def can_review(user, book_id):
    """Được đánh giá nếu đã từng mượn sách hoặc đã đọc/tải bản số."""
    if not user.is_authenticated:
        return False
    borrowed = db.session.scalar(select(func.count(Borrowing.id)).where(
        Borrowing.user_id == user.id, Borrowing.book_id == book_id,
        Borrowing.status.in_(('borrowing', 'returned'))))
    read = db.session.scalar(select(func.count(AccessLog.id)).where(
        AccessLog.user_id == user.id, AccessLog.book_id == book_id,
        AccessLog.action.in_(('read', 'download'))))
    return bool(borrowed or read)


def save_review(user, book_id, rating, comment):
    if not can_review(user, book_id):
        raise BusinessError('Bạn chỉ có thể đánh giá sau khi đã mượn hoặc đọc tài liệu này')
    if rating not in range(1, 6):
        raise BusinessError('Vui lòng chọn số sao từ 1 đến 5')
    if len(comment) > 1000:
        raise BusinessError('Nội dung đánh giá tối đa 1000 ký tự')
    review = Review.query.filter_by(book_id=book_id, user_id=user.id).first()
    if review is None:
        review = Review(book_id=book_id, user_id=user.id)
        db.session.add(review)
    review.rating = rating
    review.comment = comment
    db.session.commit()
