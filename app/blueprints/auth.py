"""Đăng nhập, đăng ký, đăng xuất."""
import re
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import User

bp = Blueprint('auth', __name__)

USERNAME_RE = re.compile(r'^[A-Za-z0-9_.]{3,50}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE = re.compile(r'^[0-9]{10,11}$')


def _safe_next(target):
    """Chỉ cho chuyển hướng về đường dẫn nội bộ (chống open redirect)."""
    if target and not urlparse(target).netloc and target.startswith('/') and not target.startswith('//'):
        return target
    return None


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter((User.username == username) | (User.email == username)).first()
        # Không phân biệt "sai tài khoản" hay "sai mật khẩu" để tránh dò tên đăng nhập
        if not user or not user.check_password(password):
            flash('Tên đăng nhập hoặc mật khẩu không chính xác', 'error')
        elif user.status == 'banned':
            flash('Tài khoản của bạn đã bị khóa. Vui lòng liên hệ quản trị viên.', 'error')
        elif user.status == 'inactive':
            flash('Tài khoản của bạn đang bị tạm ngưng. Vui lòng liên hệ quản trị viên.', 'warning')
        else:
            session.clear()  # làm mới phiên, chống session fixation
            login_user(user)
            flash(f'Đăng nhập thành công! Chào mừng {user.full_name}', 'success')
            return redirect(_safe_next(request.args.get('next')) or url_for('main.index'))
    return render_template('auth/login.html', tab='login')


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = request.form
    if request.method == 'POST':
        username = form.get('username', '').strip()
        full_name = form.get('full_name', '').strip()
        email = form.get('email', '').strip()
        phone = form.get('phone', '').strip()
        password = form.get('password', '')

        errors = []
        if not USERNAME_RE.match(username):
            errors.append('Tên đăng nhập 3-50 ký tự, chỉ gồm chữ, số, dấu _ và .')
        if not full_name or len(full_name) > 100:
            errors.append('Họ tên không được để trống (tối đa 100 ký tự)')
        if not EMAIL_RE.match(email):
            errors.append('Email không hợp lệ')
        if phone and not PHONE_RE.match(phone):
            errors.append('Số điện thoại không hợp lệ')
        if len(password) < 6:
            errors.append('Mật khẩu phải có ít nhất 6 ký tự')
        if password != form.get('confirm_password', ''):
            errors.append('Mật khẩu xác nhận không khớp')
        if User.query.filter_by(username=username).first():
            errors.append('Tên đăng nhập đã tồn tại')
        if User.query.filter_by(email=email).first():
            errors.append('Email đã được sử dụng')

        if errors:
            flash('\n'.join(errors), 'error')
        else:
            user = User(username=username, full_name=full_name, email=email, phone=phone or None)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Đăng ký thành công! Vui lòng đăng nhập', 'success')
            return redirect(url_for('auth.login'))
    return render_template('auth/login.html', tab='register')


@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.clear()
    flash('Bạn đã đăng xuất', 'info')
    return redirect(url_for('auth.login'))
