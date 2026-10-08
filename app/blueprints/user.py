"""Chức năng của thành viên: sách của tôi, đặt mượn, hủy, gia hạn, thông tin cá nhân."""
import re
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import AccessLog, Borrowing, User
from ..services import (BusinessError, borrow_book, cancel_by_user, expire_pending_borrowings, get_setting,
                        get_setting_int, renew_borrowing, unpaid_fine)

bp = Blueprint('user', __name__)


@bp.route('/my-books')
@login_required
def my_books():
    expire_pending_borrowings()
    active = (Borrowing.query.filter(Borrowing.user_id == current_user.id, Borrowing.status.in_(('pending', 'borrowing')))
              .order_by(Borrowing.status.desc(), Borrowing.due_date).all())
    history = (Borrowing.query.filter(Borrowing.user_id == current_user.id, Borrowing.status.in_(('returned', 'cancelled')))
               .order_by(Borrowing.updated_at.desc()).limit(50).all())
    reading = (AccessLog.query.filter(AccessLog.user_id == current_user.id, AccessLog.action.in_(('read', 'download')))
               .order_by(AccessLog.created_at.desc()).limit(50).all())
    hold_days = get_setting_int('pending_expire_days', 3)
    deadlines = {b.id: b.created_at.date() + timedelta(days=hold_days) for b in active if b.status == 'pending'}
    return render_template(
        'user/my_books.html', active=active, history=history, reading=reading,
        debt=unpaid_fine(current_user.id), deadlines=deadlines, hold_days=hold_days,
        max_renewals=get_setting_int('max_renewals', 2), renew_days=get_setting_int('renew_days', 7),
        library={k: get_setting(k) for k in ('contact_address', 'opening_hours', 'contact_phone', 'contact_email')},
    )


@bp.route('/borrow/<int:book_id>', methods=['POST'])
@login_required
def borrow(book_id):
    try:
        borrow_book(current_user, book_id)
        flash('Đặt mượn sách thành công! Vui lòng đến thư viện để lấy sách.', 'success')
        return redirect(url_for('user.my_books', new=1))
    except BusinessError as e:
        flash(str(e), 'error')
    return redirect(url_for('main.book_detail', book_id=book_id))


@bp.route('/borrowing/<int:borrow_id>/cancel', methods=['POST'])
@login_required
def cancel(borrow_id):
    try:
        cancel_by_user(current_user, borrow_id)
        flash('Đã hủy phiếu đặt mượn', 'success')
    except BusinessError as e:
        flash(str(e), 'error')
    return redirect(url_for('user.my_books'))


@bp.route('/borrowing/<int:borrow_id>/renew', methods=['POST'])
@login_required
def renew(borrow_id):
    try:
        borrowing, count, maximum = renew_borrowing(current_user, borrow_id)
        flash(f'Gia hạn thành công! Hạn mới: {borrowing.due_date:%d/%m/%Y} (đã gia hạn {count}/{maximum} lần)', 'success')
    except BusinessError as e:
        flash(str(e), 'error')
    return redirect(url_for('user.my_books'))


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_profile':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            if not full_name or len(full_name) > 100:
                flash('Họ tên không được để trống (tối đa 100 ký tự)', 'error')
            elif not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
                flash('Email không hợp lệ', 'error')
            elif phone and not re.match(r'^[0-9]{10,11}$', phone):
                flash('Số điện thoại không hợp lệ', 'error')
            elif User.query.filter(User.email == email, User.id != user.id).first():
                flash('Email đã được sử dụng bởi tài khoản khác', 'error')
            else:
                user.full_name, user.email, user.phone = full_name, email, phone or None
                user.address = request.form.get('address', '').strip()
                db.session.commit()
                flash('Cập nhật thông tin thành công!', 'success')
        elif action == 'change_password':
            new = request.form.get('new_password', '')
            if not user.check_password(request.form.get('current_password', '')):
                flash('Mật khẩu hiện tại không đúng', 'error')
            elif len(new) < 6:
                flash('Mật khẩu mới phải có ít nhất 6 ký tự', 'error')
            elif new != request.form.get('confirm_password', ''):
                flash('Mật khẩu xác nhận không khớp', 'error')
            else:
                user.set_password(new)
                db.session.commit()
                flash('Đổi mật khẩu thành công!', 'success')
        return redirect(url_for('user.profile'))

    borrowings = Borrowing.query.filter_by(user_id=user.id)
    stats = {
        'total': borrowings.filter(Borrowing.status != 'cancelled').count(),
        'borrowing': borrowings.filter_by(status='borrowing').count(),
        'returned': borrowings.filter_by(status='returned').count(),
        'overdue': sum(1 for b in borrowings.filter_by(status='borrowing') if b.is_overdue),
        'reads': AccessLog.query.filter(AccessLog.user_id == user.id, AccessLog.action.in_(('read', 'download'))).count(),
    }
    return render_template('user/profile.html', stats=stats)
