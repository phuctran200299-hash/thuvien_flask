"""Trang công khai: trang chủ, tra cứu, chi tiết tài liệu, đọc/tải tài liệu số, đánh giá."""
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, send_file,
                   session, url_for)
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select

from ..extensions import db
from ..models import (AccessLog, Author, Book, Borrowing, Category, DocumentFile, Publisher, Reservation, Review,
                      User)
from ..services import (BusinessError, can_access_document, can_review, delete_review, get_setting_int,
                        is_favorite, log_access, queue_position, save_review, toggle_favorite)
from ..utils import get_page

bp = Blueprint('main', __name__)

SORT_OPTIONS = {
    'newest': ('Mới nhất', [Book.created_at.desc(), Book.id.desc()]),
    'popular': ('Xem nhiều nhất', [Book.view_count.desc(), Book.id.desc()]),
    'title_asc': ('Tên A-Z', [Book.title.asc()]),
    'title_desc': ('Tên Z-A', [Book.title.desc()]),
    'year_desc': ('Năm xuất bản (mới - cũ)', [Book.publish_year.desc(), Book.id.desc()]),
    'year_asc': ('Năm xuất bản (cũ - mới)', [Book.publish_year.asc(), Book.id.desc()]),
}


@bp.route('/')
def index():
    featured = Book.query.order_by(Book.created_at.desc(), Book.id.desc()).limit(12).all()
    stats = {
        'books': db.session.scalar(select(func.count(Book.id))),
        'digital': db.session.scalar(select(func.count(DocumentFile.id))),
        'members': db.session.scalar(select(func.count(User.id)).where(User.role == 'member')),
        'reads': db.session.scalar(select(func.count(AccessLog.id)).where(AccessLog.action.in_(('read', 'download')))),
    }
    categories = Category.query.order_by(Category.name).all()
    return render_template('main/index.html', featured=featured, stats=stats, categories=categories)


@bp.route('/books')
def books():
    args = request.args
    search = args.get('search', '').strip()
    category_ids = [int(c) for c in args.getlist('category') if c.isdigit()]
    author_id = args.get('author', type=int) or 0
    publisher_id = args.get('publisher', type=int) or 0
    year_from = args.get('year_from', type=int) or 0
    year_to = args.get('year_to', type=int) or 0
    availability = args.get('availability') if args.get('availability') in ('available', 'unavailable') else 'all'
    digital_only = bool(args.get('digital'))
    sort = args.get('sort') if args.get('sort') in SORT_OPTIONS else 'newest'

    stmt = select(Book).outerjoin(Author, Book.author_id == Author.id).outerjoin(Publisher, Book.publisher_id == Publisher.id)
    if search:
        like = f'%{search}%'
        # Tìm theo tên, tác giả, NXB, ISBN, từ khóa và mô tả
        stmt = stmt.where(or_(Book.title.ilike(like), Author.name.ilike(like), Publisher.name.ilike(like),
                              Book.isbn.ilike(like), Book.keywords.ilike(like), Book.description.ilike(like)))
    if category_ids:
        stmt = stmt.where(Book.category_id.in_(category_ids))
    if author_id:
        stmt = stmt.where(Book.author_id == author_id)
    if publisher_id:
        stmt = stmt.where(Book.publisher_id == publisher_id)
    if year_from:
        stmt = stmt.where(Book.publish_year >= year_from)
    if year_to:
        stmt = stmt.where(Book.publish_year <= year_to)
    if availability == 'available':
        stmt = stmt.where(Book.available > 0)
    elif availability == 'unavailable':
        stmt = stmt.where(Book.available == 0)
    if digital_only:
        stmt = stmt.where(Book.files.any())

    pagination = db.paginate(stmt.order_by(*SORT_OPTIONS[sort][1]), page=get_page(), per_page=20, error_out=False)

    book_count = (select(func.count(Book.id)).where(Book.category_id == Category.id).correlate(Category).scalar_subquery())
    categories = db.session.execute(select(Category, book_count).order_by(Category.name)).all()

    return render_template(
        'main/books.html', pagination=pagination, categories=categories,
        authors=Author.query.order_by(Author.name).all(), publishers=Publisher.query.order_by(Publisher.name).all(),
        sort_options=SORT_OPTIONS,
        f=dict(search=search, category_ids=category_ids, author=author_id, publisher=publisher_id,
               year_from=year_from or '', year_to=year_to or '', availability=availability,
               digital=digital_only, sort=sort),
    )


@bp.route('/books/<int:book_id>')
def book_detail(book_id):
    book = db.get_or_404(Book, book_id)

    # Ghi nhận lượt xem (mỗi phiên chỉ tính 1 lần cho mỗi tài liệu)
    viewed = session.get('viewed_books', [])
    if book_id not in viewed:
        session['viewed_books'] = (viewed + [book_id])[-200:]
        book.view_count += 1
        log_access(book.id, 'view')

    can_read, _ = can_access_document(book, 'read')
    can_download, _ = can_access_document(book, 'download')

    active_borrow = my_review = my_reservation = None
    reviewable = favorite = False
    if current_user.is_authenticated:
        active_borrow = Borrowing.query.filter(Borrowing.user_id == current_user.id, Borrowing.book_id == book_id,
                                               Borrowing.status.in_(('pending', 'borrowing'))).first()
        reviewable = can_review(current_user, book_id)
        my_review = Review.query.filter_by(book_id=book_id, user_id=current_user.id).first()
        my_reservation = Reservation.query.filter_by(book_id=book_id, user_id=current_user.id, status='waiting').first()
        favorite = is_favorite(current_user.id, book_id)
    queue_length = Reservation.query.filter_by(book_id=book_id, status='waiting').count()

    rating = db.session.execute(select(func.count(Review.id), func.avg(Review.rating * 1.0))
                                .where(Review.book_id == book_id)).one()
    related = []
    if book.category_id:
        related = (Book.query.filter(Book.category_id == book.category_id, Book.id != book.id)
                   .order_by(Book.view_count.desc(), Book.id.desc()).limit(4).all())

    return render_template(
        'main/book_detail.html', book=book, can_read=can_read, can_download=can_download,
        active_borrow=active_borrow, reviewable=reviewable, my_review=my_review, favorite=favorite,
        my_reservation=my_reservation, queue_position=queue_position(my_reservation) if my_reservation else None,
        queue_length=queue_length,
        rating_count=rating[0], rating_avg=round(rating[1], 1) if rating[1] else None, related=related,
        rules={k: get_setting_int(k, d) for k, d in (('max_borrow_days', 14), ('max_renewals', 2),
                                                      ('fine_per_day', 5000), ('max_books_per_user', 5))},
    )


def _get_file_or_deny(file_id, action):
    doc = db.get_or_404(DocumentFile, file_id)
    allowed, reason = can_access_document(doc.book, action)
    if not allowed:
        flash(reason, 'error')
        target = (url_for('main.book_detail', book_id=doc.book_id) if current_user.is_authenticated
                  else url_for('auth.login', next=request.path))
        return doc, redirect(target)
    return doc, None


@bp.route('/read/<int:file_id>')
def read(file_id):
    doc, denied = _get_file_or_deny(file_id, 'read')
    if denied:
        return denied
    log_access(doc.book_id, 'read', doc.id)
    can_download, _ = can_access_document(doc.book, 'download')
    others = [f for f in doc.book.files if f.id != doc.id]
    return render_template('main/read.html', doc=doc, can_download=can_download, others=others)


@bp.route('/document/<int:file_id>')
def document(file_id):
    """Phát tệp tài liệu số. ?download=1 để tải về (ghi lịch sử download)."""
    is_download = request.args.get('download') == '1'
    doc, denied = _get_file_or_deny(file_id, 'download' if is_download else 'read')
    if denied:
        return denied
    path = Path(current_app.config['DOCUMENT_FOLDER']) / Path(doc.stored_name).name
    if not path.is_file():
        abort(404)
    if is_download:
        log_access(doc.book_id, 'download', doc.id)
    response = send_file(path, mimetype=doc.mime_type, as_attachment=is_download,
                         download_name=doc.original_name, max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.route('/books/<int:book_id>/review', methods=['POST'])
@login_required
def review(book_id):
    db.get_or_404(Book, book_id)
    try:
        save_review(current_user, book_id, request.form.get('rating', type=int) or 0,
                    request.form.get('comment', '').strip())
        flash('Cảm ơn bạn đã đánh giá!', 'success')
    except BusinessError as e:
        flash(str(e), 'error')
    return redirect(url_for('main.book_detail', book_id=book_id) + '#reviews')


@bp.route('/reviews/<int:review_id>/delete', methods=['POST'])
@login_required
def review_delete(review_id):
    try:
        book_id = delete_review(current_user, review_id)
        flash('Đã xóa đánh giá', 'success')
    except BusinessError as e:
        flash(str(e), 'error')
        return redirect(request.referrer or url_for('main.index'))
    # Quản trị viên xóa từ trang kiểm duyệt thì quay lại trang đó
    return redirect(request.referrer or url_for('main.book_detail', book_id=book_id))


@bp.route('/books/<int:book_id>/favorite', methods=['POST'])
@login_required
def favorite(book_id):
    db.get_or_404(Book, book_id)
    added = toggle_favorite(current_user, book_id)
    flash('Đã thêm vào tủ sách yêu thích' if added else 'Đã bỏ khỏi tủ sách yêu thích', 'success')
    return redirect(request.referrer or url_for('main.book_detail', book_id=book_id))
