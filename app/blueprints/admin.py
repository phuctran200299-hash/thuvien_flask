"""Trang quản trị dành cho quản trị viên / cán bộ thư viện."""
import csv
import io
from collections import Counter
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select

from ..extensions import db
from ..models import (AccessLog, Author, Book, Borrowing, Category, DocumentFile, Favorite, Notification, Publisher,
                      Reservation, Review, User)
from ..services import (BusinessError, admin_create_borrowing, admin_update_borrowing, all_settings, calculate_fine,
                        expire_pending_borrowings, notify, send_due_reminders, serve_queue, unpaid_fine,
                        update_settings)
from .auth import EMAIL_RE, PHONE_RE, USERNAME_RE
from ..utils import UploadError, delete_upload, get_page, save_upload

bp = Blueprint('admin', __name__)


@bp.before_request
def require_admin():
    if not current_user.is_authenticated:
        flash('Vui lòng đăng nhập để tiếp tục', 'warning')
        return redirect(url_for('auth.login', next=request.path))
    if not current_user.is_admin:
        abort(403)


@bp.context_processor
def inject_admin():
    pending = db.session.scalar(select(func.count(Borrowing.id)).where(Borrowing.status == 'pending'))
    return {'pending_count': pending}


# ================================================
# DASHBOARD
# ================================================
@bp.route('/')
def dashboard():
    today = date.today()
    month_start = datetime(today.year, today.month, 1)
    count = lambda stmt: db.session.scalar(stmt)  # noqa: E731
    stats = {
        'books': count(select(func.count(Book.id))),
        'files': count(select(func.count(DocumentFile.id))),
        'members': count(select(func.count(User.id)).where(User.role == 'member')),
        'borrowing': count(select(func.count(Borrowing.id)).where(Borrowing.status == 'borrowing')),
        'overdue': count(select(func.count(Borrowing.id)).where(Borrowing.status == 'borrowing', Borrowing.due_date < today)),
        'pending': count(select(func.count(Borrowing.id)).where(Borrowing.status == 'pending')),
        'reads_month': count(select(func.count(AccessLog.id)).where(
            AccessLog.action.in_(('read', 'download')), AccessLog.created_at >= month_start)),
    }
    recent_books = Book.query.order_by(Book.created_at.desc(), Book.id.desc()).limit(5).all()
    recent_borrows = Borrowing.query.order_by(Borrowing.updated_at.desc()).limit(8).all()
    return render_template('admin/dashboard.html', stats=stats, recent_books=recent_books, recent_borrows=recent_borrows)


# ================================================
# QUẢN LÝ TÀI LIỆU
# ================================================
def _find_or_create(model, name):
    name = (name or '').strip()
    if not name:
        return None
    obj = model.query.filter_by(name=name).first()
    if obj is None:
        obj = model(name=name)
        db.session.add(obj)
    return obj


@bp.route('/books')
def books():
    search = request.args.get('search', '').strip()
    category = request.args.get('category', type=int) or 0
    stmt = select(Book).outerjoin(Author, Book.author_id == Author.id)
    if search:
        like = f'%{search}%'
        stmt = stmt.where(or_(Book.title.ilike(like), Author.name.ilike(like), Book.isbn.ilike(like), Book.keywords.ilike(like)))
    if category:
        stmt = stmt.where(Book.category_id == category)
    pagination = db.paginate(stmt.order_by(Book.created_at.desc(), Book.id.desc()), page=get_page(), per_page=15, error_out=False)
    return render_template('admin/books.html', pagination=pagination, search=search, category=category,
                           categories=Category.query.order_by(Category.name).all())


@bp.route('/books/new', methods=['GET', 'POST'])
@bp.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
def book_form(book_id=None):
    book = db.get_or_404(Book, book_id) if book_id else None
    if request.method == 'POST':
        form = request.form
        title = form.get('title', '').strip()
        isbn = form.get('isbn', '').strip() or None
        quantity = max(0, form.get('quantity', type=int) or 0)
        year = form.get('publish_year', type=int)
        out_count = (book.quantity - book.available) if book else 0  # số cuốn đang được mượn/giữ

        errors = []
        if not title:
            errors.append('Vui lòng nhập tên tài liệu')
        if year is not None and not (1000 <= year <= date.today().year + 1):
            errors.append('Năm xuất bản không hợp lệ')
        if isbn and Book.query.filter(Book.isbn == isbn, Book.id != (book_id or 0)).first():
            errors.append('Mã ISBN đã tồn tại')
        if quantity < out_count:
            errors.append(f'Số lượng không được nhỏ hơn số cuốn đang được mượn/giữ ({out_count})')

        image = None
        if not errors and request.files.get('image') and request.files['image'].filename:
            try:
                image = save_upload(request.files['image'], 'image')['filename']
            except UploadError as e:
                errors.append(f'Ảnh bìa: {e}')

        if errors:
            flash('\n'.join(errors), 'error')
            return render_template('admin/book_form.html', book=book, form=form, **_book_form_options())

        is_new = book is None
        if is_new:
            book = Book()
            db.session.add(book)
        old_image = book.image
        book.title, book.isbn, book.publish_year = title, isbn, year
        book.category_id = form.get('category_id', type=int) or None
        book.author = _find_or_create(Author, form.get('author_name'))
        book.publisher = _find_or_create(Publisher, form.get('publisher_name'))
        book.keywords = form.get('keywords', '').strip()
        book.description = form.get('description', '').strip()
        book.quantity, book.available = quantity, quantity - out_count
        book.access_level = 'public' if form.get('access_level') == 'public' else 'member'
        book.allow_download = bool(form.get('allow_download'))
        if image:
            book.image = image
        if not is_new:
            serve_queue(book)  # tăng số lượng thì giữ sách cho người đang chờ đặt trước
        db.session.commit()
        if image and old_image:
            delete_upload(old_image, 'image')

        # Tải lên tệp tài liệu số (nhiều tệp)
        file_errors = []
        for upload in request.files.getlist('documents'):
            if not upload or not upload.filename:
                continue
            try:
                saved = save_upload(upload, 'document')
                db.session.add(DocumentFile(book_id=book.id, original_name=upload.filename[:255],
                                            stored_name=saved['filename'], mime_type=saved['mime'],
                                            file_size=saved['size'], uploaded_by=current_user.id))
            except UploadError as e:
                file_errors.append(f'{upload.filename}: {e}')
        db.session.commit()

        if file_errors:
            flash('Đã lưu tài liệu nhưng một số tệp lỗi:\n' + '\n'.join(file_errors), 'warning')
            return redirect(url_for('admin.book_form', book_id=book.id))
        flash('Thêm tài liệu thành công!' if is_new else 'Cập nhật tài liệu thành công!', 'success')
        return redirect(url_for('admin.books'))

    return render_template('admin/book_form.html', book=book, form={}, **_book_form_options())


def _book_form_options():
    return {'categories': Category.query.order_by(Category.name).all(),
            'authors': Author.query.order_by(Author.name).all(),
            'publishers': Publisher.query.order_by(Publisher.name).all()}


@bp.route('/books/<int:book_id>/delete', methods=['POST'])
def book_delete(book_id):
    book = db.get_or_404(Book, book_id)
    active = Borrowing.query.filter(Borrowing.book_id == book_id, Borrowing.status.in_(('pending', 'borrowing'))).count()
    if active:
        flash('Không thể xóa tài liệu đang có người mượn hoặc đặt mượn', 'error')
        return redirect(url_for('admin.books'))
    stored = [f.stored_name for f in book.files]
    image = book.image
    # access_logs.file_id không cascade trên SQL Server nên xóa log trước
    AccessLog.query.filter_by(book_id=book_id).delete()
    Borrowing.query.filter_by(book_id=book_id).delete()
    Reservation.query.filter_by(book_id=book_id).delete()
    Favorite.query.filter_by(book_id=book_id).delete()
    db.session.delete(book)
    db.session.commit()
    for name in stored:
        delete_upload(name, 'document')
    delete_upload(image, 'image')
    flash('Xóa tài liệu thành công', 'success')
    return redirect(url_for('admin.books'))


@bp.route('/files/<int:file_id>/delete', methods=['POST'])
def file_delete(file_id):
    doc = db.get_or_404(DocumentFile, file_id)
    book_id, stored, name = doc.book_id, doc.stored_name, doc.original_name
    AccessLog.query.filter_by(file_id=file_id).update({'file_id': None})
    db.session.delete(doc)
    db.session.commit()
    delete_upload(stored, 'document')
    flash(f'Đã xóa tệp {name}', 'success')
    return redirect(url_for('admin.book_form', book_id=book_id))


# ================================================
# DANH MỤC / TÁC GIẢ / NHÀ XUẤT BẢN (CRUD dùng chung)
# ================================================
TAXONOMIES = {
    'categories': (Category, 'category_id', 'danh mục', 'Quản lý danh mục'),
    'authors': (Author, 'author_id', 'tác giả', 'Quản lý tác giả'),
    'publishers': (Publisher, 'publisher_id', 'nhà xuất bản', 'Quản lý nhà xuất bản'),
}


@bp.route('/<any(categories, authors, publishers):kind>', methods=['GET', 'POST'])
def taxonomy(kind):
    model, fk, label, title = TAXONOMIES[kind]
    if request.method == 'POST':
        item_id = request.form.get('id', type=int) or 0
        if request.form.get('action') == 'delete':
            item = db.get_or_404(model, item_id)
            used = Book.query.filter(getattr(Book, fk) == item_id).count()
            if used:
                flash(f'Không thể xóa: đang có {used} tài liệu thuộc {label} này.', 'error')
            else:
                db.session.delete(item)
                db.session.commit()
                flash(f'Đã xóa {label}', 'success')
        else:
            name = request.form.get('name', '').strip()
            if not name or len(name) > 150:
                flash(f'Tên {label} không được để trống (tối đa 150 ký tự)', 'error')
            elif model.query.filter(model.name == name, model.id != item_id).first():
                flash(f'Tên {label} đã tồn tại', 'error')
            else:
                item = db.get_or_404(model, item_id) if item_id else model()
                item.name = name
                item.description = request.form.get('description', '').strip()
                db.session.add(item)
                db.session.commit()
                flash(f'Đã lưu {label}', 'success')
        return redirect(url_for('admin.taxonomy', kind=kind))

    search = request.args.get('search', '').strip()
    count = select(func.count(Book.id)).where(getattr(Book, fk) == model.id).correlate(model).scalar_subquery()
    stmt = select(model, count).order_by(model.name)
    if search:
        stmt = stmt.where(model.name.ilike(f'%{search}%'))
    editing = db.session.get(model, request.args.get('edit', type=int) or 0)
    return render_template('admin/taxonomy.html', kind=kind, label=label, title=title, search=search,
                           items=db.session.execute(stmt).all(), editing=editing)


# ================================================
# NGƯỜI DÙNG
# ================================================
@bp.route('/users', methods=['GET', 'POST'])
def users():
    if request.method == 'POST':
        user = db.get_or_404(User, request.form.get('user_id', type=int) or 0)
        field, value = request.form.get('field'), request.form.get('value', '')
        if field == 'role' and value in User.ROLES:
            if user.id == current_user.id and value != 'admin':
                flash('Bạn không thể tự hạ quyền quản trị của chính mình', 'error')
            else:
                user.role = value
                db.session.commit()
                flash('Cập nhật vai trò thành công', 'success')
        elif field == 'status' and value in User.STATUSES:
            if user.id == current_user.id and value != 'active':
                flash('Bạn không thể tự khóa tài khoản của chính mình', 'error')
            else:
                user.status = value
                db.session.commit()
                flash('Cập nhật trạng thái thành công', 'success')
        else:
            flash('Giá trị không hợp lệ', 'error')
        return redirect(request.referrer or url_for('admin.users'))

    search = request.args.get('search', '').strip()
    role = request.args.get('role') if request.args.get('role') in User.ROLES else ''
    status = request.args.get('status') if request.args.get('status') in User.STATUSES else ''
    stmt = select(User)
    if search:
        like = f'%{search}%'
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like), User.username.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)
    pagination = db.paginate(stmt.order_by(User.created_at.desc(), User.id.desc()), page=get_page(), per_page=20, error_out=False)
    return render_template('admin/users.html', pagination=pagination, search=search, role=role, status=status)


def _validate_user_form(form, user=None):
    """Kiểm tra form thêm/sửa người dùng. Trả về danh sách lỗi."""
    errors = []
    user_id = user.id if user else 0
    if user is None:
        username = form.get('username', '').strip()
        if not USERNAME_RE.match(username):
            errors.append('Tên đăng nhập 3-50 ký tự, chỉ gồm chữ, số, dấu _ và .')
        elif User.query.filter_by(username=username).first():
            errors.append('Tên đăng nhập đã tồn tại')
        if len(form.get('password', '')) < 6:
            errors.append('Mật khẩu phải có ít nhất 6 ký tự')
    full_name = form.get('full_name', '').strip()
    email = form.get('email', '').strip()
    phone = form.get('phone', '').strip()
    if not full_name or len(full_name) > 100:
        errors.append('Họ tên không được để trống (tối đa 100 ký tự)')
    if not EMAIL_RE.match(email):
        errors.append('Email không hợp lệ')
    elif User.query.filter(User.email == email, User.id != user_id).first():
        errors.append('Email đã được sử dụng')
    if phone and not PHONE_RE.match(phone):
        errors.append('Số điện thoại không hợp lệ')
    if form.get('role') not in User.ROLES or form.get('status') not in User.STATUSES:
        errors.append('Vai trò hoặc trạng thái không hợp lệ')
    elif user and user.id == current_user.id and (form.get('role') != 'admin' or form.get('status') != 'active'):
        errors.append('Bạn không thể tự hạ quyền hoặc khóa tài khoản của chính mình')
    return errors


def _apply_user_form(user, form):
    user.full_name = form.get('full_name', '').strip()
    user.email = form.get('email', '').strip()
    user.phone = form.get('phone', '').strip() or None
    user.address = form.get('address', '').strip()
    user.role, user.status = form.get('role'), form.get('status')


@bp.route('/users/new', methods=['GET', 'POST'])
def user_new():
    form = request.form
    if request.method == 'POST':
        errors = _validate_user_form(form)
        if errors:
            flash('\n'.join(errors), 'error')
        else:
            user = User(username=form.get('username', '').strip())
            _apply_user_form(user, form)
            user.set_password(form.get('password', ''))
            db.session.add(user)
            db.session.commit()
            flash(f'Đã tạo tài khoản {user.username}', 'success')
            return redirect(url_for('admin.user_detail', user_id=user.id))
    return render_template('admin/user_form.html', user=None, form=form)


@bp.route('/users/<int:user_id>', methods=['GET', 'POST'])
def user_detail(user_id):
    user = db.get_or_404(User, user_id)
    form = request.form
    if request.method == 'POST':
        errors = _validate_user_form(form, user)
        if errors:
            flash('\n'.join(errors), 'error')
            return render_template('admin/user_form.html', user=user, form=form)
        _apply_user_form(user, form)
        db.session.commit()
        flash('Cập nhật thông tin người dùng thành công', 'success')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if request.args.get('edit'):
        return render_template('admin/user_form.html', user=user, form={})
    borrowings = Borrowing.query.filter_by(user_id=user_id).order_by(Borrowing.created_at.desc()).limit(50).all()
    logs = AccessLog.query.filter_by(user_id=user_id).order_by(AccessLog.created_at.desc()).limit(30).all()
    reservations = Reservation.query.filter_by(user_id=user_id, status='waiting').order_by(Reservation.created_at).all()
    return render_template('admin/user_detail.html', user=user, borrowings=borrowings, logs=logs,
                           reservations=reservations, debt=unpaid_fine(user_id))


@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
def user_reset_password(user_id):
    user = db.get_or_404(User, user_id)
    password = request.form.get('password', '')
    if len(password) < 6:
        flash('Mật khẩu mới phải có ít nhất 6 ký tự', 'error')
    else:
        user.set_password(password)
        notify(user.id, 'Mật khẩu của bạn vừa được quản trị viên đặt lại. Hãy đổi mật khẩu mới sau khi đăng nhập.',
               '/profile')
        db.session.commit()
        flash(f'Đã đặt lại mật khẩu cho {user.username}', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))


@bp.route('/users/<int:user_id>/delete', methods=['POST'])
def user_delete(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash('Bạn không thể xóa tài khoản của chính mình', 'error')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    active = Borrowing.query.filter(Borrowing.user_id == user_id, Borrowing.status.in_(('pending', 'borrowing'))).count()
    if active or unpaid_fine(user_id):
        flash('Không thể xóa: người dùng còn sách đang mượn/chờ lấy hoặc còn nợ tiền phạt. '
              'Có thể chuyển trạng thái sang "Bị khóa".', 'error')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    # Giữ lại lịch sử truy cập (ẩn danh) để thống kê; xóa dữ liệu cá nhân còn lại
    AccessLog.query.filter_by(user_id=user_id).update({'user_id': None})
    for model in (Notification, Favorite, Reservation, Review):
        model.query.filter_by(user_id=user_id).delete()
    for borrowing in Borrowing.query.filter_by(user_id=user_id).all():
        db.session.delete(borrowing)  # xóa kèm lịch sử gia hạn
    DocumentFile.query.filter_by(uploaded_by=user_id).update({'uploaded_by': None})
    db.session.delete(user)
    db.session.commit()
    flash(f'Đã xóa tài khoản {user.username}', 'success')
    return redirect(url_for('admin.users'))


# ================================================
# MƯỢN - TRẢ
# ================================================
BORROW_FILTERS = {
    'all': 'Tất cả', 'pending': 'Chờ lấy sách', 'borrowing': 'Đang mượn', 'overdue': 'Quá hạn',
    'returned': 'Đã trả', 'unpaid': 'Chưa đóng phạt', 'cancelled': 'Đã hủy',
}


def _borrow_filter(stmt, status):
    if status == 'overdue':
        return stmt.where(Borrowing.status == 'borrowing', Borrowing.due_date < date.today())
    if status == 'unpaid':
        return stmt.where(Borrowing.fine_amount > 0, Borrowing.fine_paid == db.false())
    if status in ('pending', 'borrowing', 'returned', 'cancelled'):
        return stmt.where(Borrowing.status == status)
    return stmt


@bp.route('/borrowing')
def borrowing():
    expire_pending_borrowings()
    send_due_reminders()
    status = request.args.get('status') if request.args.get('status') in BORROW_FILTERS else 'all'
    search = request.args.get('search', '').strip()
    stmt = select(Borrowing).join(User, Borrowing.user_id == User.id).join(Book, Borrowing.book_id == Book.id)
    stmt = _borrow_filter(stmt, status)
    if search:
        like = f'%{search}%'
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like), Book.title.ilike(like)))
    pagination = db.paginate(stmt.order_by(Borrowing.created_at.desc(), Borrowing.id.desc()),
                             page=get_page(), per_page=20, error_out=False)
    counts = {key: db.session.scalar(_borrow_filter(select(func.count(Borrowing.id)), key)) for key in BORROW_FILTERS}
    return render_template('admin/borrowing.html', pagination=pagination, status=status, search=search,
                           filters=BORROW_FILTERS, counts=counts, calculate_fine=calculate_fine)


@bp.route('/borrowing/new', methods=['POST'])
def borrowing_new():
    """Lập phiếu mượn tại quầy: nhập tên đăng nhập/email người đọc và mã tài liệu/ISBN."""
    reader = request.form.get('reader', '').strip()
    book_code = request.form.get('book', '').strip().lstrip('#')
    user = User.query.filter((User.username == reader) | (User.email == reader)).first() if reader else None
    book = None
    if book_code:
        book = Book.query.filter_by(isbn=book_code).first()
        if book is None and book_code.isdigit():
            book = db.session.get(Book, int(book_code))
    if not user:
        flash('Không tìm thấy người đọc với tên đăng nhập/email đã nhập', 'error')
    elif not book:
        flash('Không tìm thấy tài liệu với mã/ISBN đã nhập', 'error')
    else:
        try:
            borrowing = admin_create_borrowing(user.id, book.id)
            flash(f'Đã lập phiếu #{borrowing.id}: {user.full_name} mượn "{book.title}", '
                  f'hạn trả {borrowing.due_date:%d/%m/%Y}', 'success')
        except BusinessError as e:
            flash(str(e), 'error')
    return redirect(url_for('admin.borrowing'))


@bp.route('/reservations')
def reservations():
    items = (Reservation.query.filter_by(status='waiting')
             .order_by(Reservation.book_id, Reservation.created_at, Reservation.id).all())
    return render_template('admin/reservations.html', items=items)


@bp.route('/reservations/<int:reservation_id>/cancel', methods=['POST'])
def reservation_cancel(reservation_id):
    reservation = Reservation.query.filter_by(id=reservation_id, status='waiting').first_or_404()
    reservation.status = 'cancelled'
    notify(reservation.user_id, f'Đăng ký chờ sách "{reservation.book.title}" đã bị thư viện hủy.', '/my-books')
    db.session.commit()
    flash('Đã hủy đăng ký chờ', 'success')
    return redirect(url_for('admin.reservations'))


# ================================================
# KIỂM DUYỆT ĐÁNH GIÁ
# ================================================
@bp.route('/reviews')
def reviews():
    search = request.args.get('search', '').strip()
    rating = request.args.get('rating', type=int) or 0
    stmt = select(Review).join(Book, Review.book_id == Book.id).join(User, Review.user_id == User.id)
    if search:
        like = f'%{search}%'
        stmt = stmt.where(or_(Book.title.ilike(like), User.full_name.ilike(like), Review.comment.ilike(like)))
    if 1 <= rating <= 5:
        stmt = stmt.where(Review.rating == rating)
    pagination = db.paginate(stmt.order_by(Review.created_at.desc(), Review.id.desc()),
                             page=get_page(), per_page=20, error_out=False)
    return render_template('admin/reviews.html', pagination=pagination, search=search, rating=rating)


@bp.route('/borrowing/<int:borrow_id>/<any(confirm_pickup, confirm_return, cancel, mark_paid):action>', methods=['POST'])
def borrowing_action(borrow_id, action):
    try:
        flash(admin_update_borrowing(borrow_id, action), 'success')
    except BusinessError as e:
        flash(str(e), 'error')
    return redirect(request.referrer or url_for('admin.borrowing'))


# ================================================
# LỊCH SỬ TRUY CẬP TÀI LIỆU
# ================================================
@bp.route('/access-logs')
def access_logs():
    action = request.args.get('action') if request.args.get('action') in AccessLog.ACTION_LABELS else ''
    search = request.args.get('search', '').strip()
    date_from, date_to = request.args.get('from', ''), request.args.get('to', '')
    stmt = select(AccessLog).join(Book, AccessLog.book_id == Book.id).outerjoin(User, AccessLog.user_id == User.id)
    if action:
        stmt = stmt.where(AccessLog.action == action)
    if search:
        like = f'%{search}%'
        stmt = stmt.where(or_(Book.title.ilike(like), User.full_name.ilike(like), User.username.ilike(like)))
    try:
        if date_from:
            stmt = stmt.where(AccessLog.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        if date_to:
            stmt = stmt.where(AccessLog.created_at < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    except ValueError:
        flash('Ngày không hợp lệ', 'error')
    pagination = db.paginate(stmt.order_by(AccessLog.created_at.desc(), AccessLog.id.desc()),
                             page=get_page(), per_page=30, error_out=False)
    since = datetime.now() - timedelta(days=30)
    summary = {a: db.session.scalar(select(func.count(AccessLog.id)).where(AccessLog.action == a, AccessLog.created_at >= since))
               for a in AccessLog.ACTION_LABELS}
    return render_template('admin/access_logs.html', pagination=pagination, action=action, search=search,
                           date_from=date_from, date_to=date_to, summary=summary)


# ================================================
# THỐNG KÊ & BÁO CÁO
# ================================================
@bp.route('/statistics')
def statistics():
    today = date.today()

    # Lượt mượn 12 tháng gần nhất (tính trong Python để chạy được trên mọi hệ CSDL)
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.insert(0, (y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    first_day = date(*months[0], 1)
    borrow_dates = db.session.scalars(select(Borrowing.borrow_date).where(
        Borrowing.status != 'cancelled', Borrowing.borrow_date >= first_day)).all()
    month_counter = Counter((d.year, d.month) for d in borrow_dates)
    monthly = [{'label': f'{mm:02d}/{yy}', 'value': month_counter.get((yy, mm), 0)} for yy, mm in months]

    # Lượt truy cập tài liệu số 30 ngày gần nhất theo loại hoạt động
    start = today - timedelta(days=29)
    rows = db.session.execute(select(AccessLog.action, AccessLog.created_at)
                              .where(AccessLog.created_at >= datetime.combine(start, datetime.min.time()))).all()
    day_counter = Counter((action, created.date()) for action, created in rows)
    days = [start + timedelta(days=i) for i in range(30)]
    access = {a: [day_counter.get((a, d), 0) for d in days] for a in ('read', 'download', 'view')}

    # Top tài liệu số được đọc/tải
    # (gom nhóm theo book_id trong subquery rồi mới join, tránh GROUP BY các cột văn bản dài trên SQL Server)
    doc_stats = (select(AccessLog.book_id,
                        func.sum(db.case((AccessLog.action == 'read', 1), else_=0)).label('reads'),
                        func.sum(db.case((AccessLog.action == 'download', 1), else_=0)).label('downloads'))
                 .where(AccessLog.action.in_(('read', 'download'))).group_by(AccessLog.book_id).subquery())
    top_docs = db.session.execute(
        select(Book, doc_stats.c.reads, doc_stats.c.downloads).join(doc_stats, doc_stats.c.book_id == Book.id)
        .order_by((doc_stats.c.reads + doc_stats.c.downloads).desc(), Book.id).limit(10)).all()

    # Top sách giấy được mượn nhiều
    borrow_stats = (select(Borrowing.book_id, func.count(Borrowing.id).label('n'))
                    .where(Borrowing.status != 'cancelled').group_by(Borrowing.book_id).subquery())
    top_borrowed = db.session.execute(
        select(Book, borrow_stats.c.n).join(borrow_stats, borrow_stats.c.book_id == Book.id)
        .order_by(borrow_stats.c.n.desc(), Book.id).limit(10)).all()

    book_count = func.count(Book.id)
    by_category = db.session.execute(
        select(Category.name, book_count).outerjoin(Book, Book.category_id == Category.id)
        .group_by(Category.name).order_by(book_count.desc())).all()

    fines = {
        'paid': db.session.scalar(select(func.coalesce(func.sum(Borrowing.fine_amount), 0)).where(Borrowing.fine_paid == db.true())) or 0,
        'unpaid': db.session.scalar(select(func.coalesce(func.sum(Borrowing.fine_amount), 0)).where(
            Borrowing.fine_amount > 0, Borrowing.fine_paid == db.false())) or 0,
    }
    return render_template('admin/statistics.html', monthly=monthly, access=access,
                           access_days=[d.strftime('%d/%m') for d in days],
                           access_totals={k: sum(v) for k, v in access.items()},
                           top_docs=top_docs, top_borrowed=top_borrowed, by_category=by_category, fines=fines,
                           now_str=datetime.now().strftime('%H:%M %d/%m/%Y'))


def _csv_cell(value):
    """Chặn CSV injection: ô bắt đầu bằng = + - @ bị Excel hiểu là công thức."""
    if value is None:
        return ''
    if isinstance(value, (datetime, date)):
        return value.strftime('%Y-%m-%d %H:%M' if isinstance(value, datetime) else '%Y-%m-%d')
    text = str(value)
    if text and text[0] in '=+-@\t\r' and not isinstance(value, (int, float)):
        text = "'" + text
    return text


@bp.route('/export/<any(books, borrowing, users, access_logs):kind>')
def export(kind):
    if kind == 'books':
        header = ['ID', 'Tên tài liệu', 'Tác giả', 'NXB', 'Năm XB', 'ISBN', 'Danh mục', 'Số lượng', 'Còn lại',
                  'Số tệp số', 'Quyền đọc', 'Cho tải', 'Lượt xem']
        rows = [[b.id, b.title, b.author_name, b.publisher_name, b.publish_year, b.isbn,
                 b.category.name if b.category else '', b.quantity, b.available, len(b.files),
                 'Công khai' if b.access_level == 'public' else 'Thành viên', 'Có' if b.allow_download else 'Không',
                 b.view_count] for b in Book.query.order_by(Book.id)]
    elif kind == 'borrowing':
        header = ['Mã phiếu', 'Người mượn', 'Email', 'Tài liệu', 'Ngày mượn', 'Hạn trả', 'Ngày trả', 'Trạng thái',
                  'Số lần gia hạn', 'Tiền phạt', 'Đã thu phạt']
        rows = [[b.id, b.user.full_name, b.user.email, b.book.title, b.borrow_date, b.due_date, b.return_date,
                 b.status_label, b.renew_count, b.fine_amount,
                 ('Đã thu' if b.fine_paid else 'Chưa thu') if b.fine_amount else '']
                for b in Borrowing.query.order_by(Borrowing.id.desc())]
    elif kind == 'users':
        header = ['ID', 'Tên đăng nhập', 'Họ tên', 'Email', 'Điện thoại', 'Vai trò', 'Trạng thái', 'Ngày tạo']
        rows = [[u.id, u.username, u.full_name, u.email, u.phone, 'Quản trị' if u.is_admin else 'Thành viên',
                 u.status, u.created_at] for u in User.query.order_by(User.id)]
    else:
        header = ['Thời gian', 'Người dùng', 'Tài liệu', 'Tệp', 'Hoạt động', 'IP']
        rows = [[log.created_at, log.user.full_name if log.user else 'Khách', log.book.title,
                 log.file.original_name if log.file else '', AccessLog.ACTION_LABELS[log.action], log.ip_address]
                for log in AccessLog.query.order_by(AccessLog.created_at.desc()).limit(50000)]

    buffer = io.StringIO()
    buffer.write('\ufeff')  # BOM để Excel đọc đúng tiếng Việt
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows([[_csv_cell(v) for v in row] for row in rows])
    filename = f'{kind}_{datetime.now():%Y%m%d_%H%M%S}.csv'
    return Response(buffer.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


# ================================================
# CÀI ĐẶT
# ================================================
@bp.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        errors = update_settings(request.form)
        if errors:
            flash('\n'.join(errors), 'error')
        else:
            flash('Cập nhật cài đặt thành công!', 'success')
        return redirect(url_for('admin.settings'))
    return render_template('admin/settings.html', settings=all_settings())
