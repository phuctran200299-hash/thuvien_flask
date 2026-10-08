"""Tầng nghiệp vụ: cài đặt hệ thống, thông báo, mượn - trả, đặt trước, tiền phạt, phân quyền tài liệu số,
lịch sử truy cập, đánh giá, tủ sách yêu thích.

Các hàm thay đổi dữ liệu tự commit khi thành công và rollback khi lỗi.
Lỗi nghiệp vụ (hiển thị được cho người dùng) được ném ra dưới dạng BusinessError.
"""
import re
from datetime import date, datetime, timedelta

from flask import request
from flask_login import current_user
from sqlalchemy import func, select

from .extensions import db
from .models import (AccessLog, Book, Borrowing, BorrowRenewal, Favorite, Notification, Reservation, Review,
                     Setting, User)


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
    ('remind_before_days', '2', 'number', 'Nhắc hạn trả trước bao nhiêu ngày'),
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
# THÔNG BÁO
# ================================================
def notify(user_id, message, link=None, dedup_key=None):
    """Thêm thông báo cho người dùng (chưa commit, commit cùng transaction của nghiệp vụ gọi nó).
    Có dedup_key thì không tạo lại thông báo đã có cùng khóa."""
    if dedup_key and db.session.scalar(select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.dedup_key == dedup_key)):
        return None
    notification = Notification(user_id=user_id, message=message[:500], link=link, dedup_key=dedup_key)
    db.session.add(notification)
    return notification


def unread_notifications(user_id):
    return db.session.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.is_read == db.false())) or 0


def mark_notifications_read(user_id, notification_id=None):
    query = Notification.query.filter_by(user_id=user_id, is_read=False)
    if notification_id:
        query = query.filter_by(id=notification_id)
    query.update({'is_read': True})
    db.session.commit()


def send_due_reminders(user_id=None):
    """Nhắc các phiếu sắp đến hạn và đã quá hạn (mỗi phiếu tối đa 1 lần/ngày), của mọi người hoặc một người.
    Trả về số thông báo đã tạo."""
    today = date.today()
    soon = today + timedelta(days=get_setting_int('remind_before_days', 2))
    query = Borrowing.query.filter(Borrowing.status == 'borrowing', Borrowing.due_date <= soon)
    if user_id:
        query = query.filter(Borrowing.user_id == user_id)
    created = 0
    for b in query.all():
        if b.due_date < today:
            message = (f'Sách "{b.book.title}" đã quá hạn trả {b.overdue_days} ngày '
                       f'(tiền phạt tạm tính {calculate_fine(b.due_date):,}đ). Vui lòng trả sách sớm.').replace(',', '.')
        else:
            when = 'hôm nay' if b.due_date == today else f'ngày {b.due_date:%d/%m/%Y}'
            message = f'Sách "{b.book.title}" đến hạn trả {when}. Bạn có thể gia hạn trong mục Sách của tôi.'
        if notify(b.user_id, message, '/my-books', dedup_key=f'due:{b.id}:{today:%Y%m%d}'):
            created += 1
    db.session.commit()
    return created


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
            notify(borrowing.user_id, f'Phiếu đặt mượn "{borrowing.book.title}" đã tự động hủy do quá hạn đến lấy sách.',
                   '/my-books')
            book = _lock_book(borrowing.book_id)
            if book:
                release_copy(book)
        return len(expired)

    return _run(work) if expired else 0


def has_active_borrow(user_id, book_id):
    return bool(db.session.scalar(select(func.count(Borrowing.id)).where(
        Borrowing.user_id == user_id, Borrowing.book_id == book_id,
        Borrowing.status.in_(('pending', 'borrowing')))))


def check_borrow_eligibility(user, book_id):
    """Kiểm tra người dùng có được mượn thêm sách này không; ném BusinessError nếu không."""
    if user.status != 'active':
        raise BusinessError('Tài khoản đang bị khóa hoặc tạm ngưng')
    debt = unpaid_fine(user.id)
    if debt > 0:
        raise BusinessError(f'Còn khoản phạt chưa thanh toán ({debt:,.0f}đ). '
                            'Vui lòng thanh toán tại thư viện trước khi mượn tiếp.'.replace(',', '.'))
    if has_active_borrow(user.id, book_id):
        raise BusinessError('Bạn đã đặt hoặc đang mượn sách này rồi')
    max_books = get_setting_int('max_books_per_user', 5)
    if count_active_borrows(user.id) >= max_books:
        raise BusinessError(f'Bạn chỉ được mượn tối đa {max_books} cuốn cùng lúc (tính cả phiếu đang chờ lấy)')


def _new_borrowing(user_id, book, status='pending'):
    # Với phiếu chờ lấy, ngày mượn/hạn trả là tạm tính; được tính lại khi thủ thư xác nhận giao sách
    borrowing = Borrowing(user_id=user_id, book_id=book.id, borrow_date=date.today(),
                          due_date=date.today() + timedelta(days=get_setting_int('max_borrow_days', 14)), status=status)
    book.available -= 1
    db.session.add(borrowing)
    # Người đang xếp hàng chờ đặt trước mà mượn được thì coi như đã nhận
    Reservation.query.filter_by(user_id=user_id, book_id=book.id, status='waiting').update({'status': 'fulfilled'})
    db.session.flush()
    return borrowing


def borrow_book(user, book_id):
    """Thành viên đặt mượn sách giấy -> tạo phiếu 'pending'."""
    expire_pending_borrowings()

    def work():
        book = _lock_book(book_id)
        if not book or book.available <= 0:
            raise BusinessError('Sách không còn sẵn để mượn')
        check_borrow_eligibility(user, book_id)
        return _new_borrowing(user.id, book)

    return _run(work)


def admin_create_borrowing(user_id, book_id):
    """Thủ thư lập phiếu mượn trực tiếp tại quầy: người đọc nhận sách ngay (trạng thái 'borrowing')."""
    expire_pending_borrowings()

    def work():
        user = db.session.get(User, user_id)
        if not user:
            raise BusinessError('Không tìm thấy người đọc')
        book = _lock_book(book_id)
        if not book:
            raise BusinessError('Không tìm thấy tài liệu')
        if book.available <= 0:
            raise BusinessError(f'Sách "{book.title}" đã hết, không còn cuốn nào sẵn tại thư viện')
        check_borrow_eligibility(user, book_id)
        return _new_borrowing(user.id, book, status='borrowing')

    return _run(work)


# ================================================
# ĐẶT TRƯỚC (HÀNG CHỜ KHI SÁCH HẾT)
# ================================================
def queue_position(reservation):
    return db.session.scalar(select(func.count(Reservation.id)).where(
        Reservation.book_id == reservation.book_id, Reservation.status == 'waiting',
        Reservation.id <= reservation.id))


def reserve_book(user, book_id):
    """Đăng ký chờ sách đang hết. Trả về vị trí trong hàng chờ."""
    book = db.session.get(Book, book_id)
    if not book or book.quantity <= 0:
        raise BusinessError('Thư viện không có bản giấy của tài liệu này')
    if book.available > 0:
        raise BusinessError('Sách vẫn còn, bạn có thể đặt mượn ngay')
    if has_active_borrow(user.id, book_id):
        raise BusinessError('Bạn đã đặt hoặc đang mượn sách này rồi')
    if Reservation.query.filter_by(user_id=user.id, book_id=book_id, status='waiting').first():
        raise BusinessError('Bạn đã đăng ký chờ sách này rồi')
    reservation = Reservation(user_id=user.id, book_id=book_id, status='waiting')
    db.session.add(reservation)
    db.session.commit()
    return queue_position(reservation)


def cancel_reservation(user, reservation_id):
    reservation = Reservation.query.filter_by(id=reservation_id, user_id=user.id, status='waiting').first()
    if not reservation:
        raise BusinessError('Không tìm thấy đăng ký chờ')
    reservation.status = 'cancelled'
    db.session.commit()


def release_copy(book):
    """Một cuốn sách được trả về kho (trả sách, hủy phiếu...): ưu tiên giữ cho người đầu hàng chờ đặt trước.
    Gọi trong transaction, book đã được khóa dòng."""
    book.available = min(book.quantity, book.available + 1)
    serve_queue(book)


def serve_queue(book):
    """Chuyển các cuốn đang sẵn thành phiếu chờ lấy cho người trong hàng chờ (theo thứ tự đăng ký).
    Người chưa đủ điều kiện mượn (nợ phạt, đủ số sách...) giữ nguyên vị trí và bị bỏ qua lượt này."""
    if book.available <= 0:
        return
    waiting = (Reservation.query.filter_by(book_id=book.id, status='waiting')
               .order_by(Reservation.created_at, Reservation.id).all())
    for reservation in waiting:
        if book.available <= 0:
            break
        try:
            check_borrow_eligibility(reservation.user, book.id)
        except BusinessError:
            continue
        _new_borrowing(reservation.user_id, book)
        notify(reservation.user_id,
               f'Sách "{book.title}" bạn đặt trước đã có. Thư viện giữ sách cho bạn '
               f'{get_setting_int("pending_expire_days", 3)} ngày, vui lòng đến nhận.', '/my-books')


def cancel_by_user(user, borrow_id):
    def work():
        borrowing = _lock_borrowing(borrow_id, user_id=user.id, status='pending')
        if not borrowing:
            raise BusinessError('Không tìm thấy phiếu đặt mượn đang chờ')
        borrowing.status = 'cancelled'
        borrowing.notes = 'Người dùng tự hủy'
        release_copy(_lock_book(borrowing.book_id))

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
            if fine:
                notify(borrowing.user_id, f'Bạn trả sách "{borrowing.book.title}" trễ hạn, tiền phạt: {fine:,}đ. '
                       'Vui lòng thanh toán tại quầy thư viện.'.replace(',', '.'), '/my-books')
            release_copy(_lock_book(borrowing.book_id))
            return (f'Đã nhận lại sách. Trả trễ, tiền phạt: {fine:,}đ'.replace(',', '.')
                    if fine else 'Đã nhận lại sách đúng hạn')

        if action == 'cancel':
            if borrowing.status != 'pending':
                raise BusinessError('Chỉ hủy được phiếu đang chờ lấy sách')
            borrowing.status = 'cancelled'
            borrowing.notes = 'Thủ thư hủy phiếu'
            notify(borrowing.user_id, f'Phiếu đặt mượn "{borrowing.book.title}" đã bị thư viện hủy.', '/my-books')
            release_copy(_lock_book(borrowing.book_id))
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


def delete_review(user, review_id):
    """Xóa đánh giá: người viết tự xóa, hoặc quản trị viên kiểm duyệt. Trả về book_id."""
    review = db.session.get(Review, review_id)
    if not review or (review.user_id != user.id and not user.is_admin):
        raise BusinessError('Không tìm thấy đánh giá')
    book_id = review.book_id
    db.session.delete(review)
    db.session.commit()
    return book_id


# ================================================
# TỦ SÁCH YÊU THÍCH
# ================================================
def is_favorite(user_id, book_id):
    return bool(db.session.scalar(select(func.count(Favorite.id)).where(
        Favorite.user_id == user_id, Favorite.book_id == book_id)))


def toggle_favorite(user, book_id):
    """Thêm/bỏ tài liệu khỏi tủ sách yêu thích. Trả về True nếu vừa thêm."""
    favorite = Favorite.query.filter_by(user_id=user.id, book_id=book_id).first()
    if favorite:
        db.session.delete(favorite)
    else:
        db.session.add(Favorite(user_id=user.id, book_id=book_id))
    db.session.commit()
    return favorite is None
