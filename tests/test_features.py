"""Kiểm thử các chức năng bổ sung: đặt trước, thông báo, yêu thích, quản trị người dùng,
lập phiếu tại quầy, kiểm duyệt đánh giá."""
from datetime import date, timedelta

import pytest

from app.models import Borrowing, Favorite, Notification, Reservation, Review, User
from app.services import (BusinessError, admin_create_borrowing, admin_update_borrowing, borrow_book,
                          delete_review, reserve_book, save_review, send_due_reminders)
from conftest import active_borrow, flashes


def make_user(db, username):
    user = User(username=username, full_name=f'Người {username}', email=f'{username}@test.vn')
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return user


def notifications_of(user):
    return [n.message for n in Notification.query.filter_by(user_id=user.id).order_by(Notification.id)]


# ---------- Đặt trước ----------
def test_chi_dat_truoc_khi_sach_het(member, book_by_title):
    with pytest.raises(BusinessError, match='đặt mượn ngay'):
        reserve_book(member, book_by_title('Marketing').id)


def test_dat_truoc_va_tu_giu_sach_khi_co_nguoi_tra(db, member, book_by_title):
    book = book_by_title('Marketing')
    book.quantity = book.available = 1
    db.session.commit()
    other = make_user(db, 'docgia2')
    third = make_user(db, 'docgia3')
    borrowing = borrow_book(other, book.id)
    admin_update_borrowing(borrowing.id, 'confirm_pickup')

    assert reserve_book(member, book.id) == 1
    assert reserve_book(third, book.id) == 2
    with pytest.raises(BusinessError, match='đã đăng ký chờ'):
        reserve_book(member, book.id)

    admin_update_borrowing(borrowing.id, 'confirm_return')
    # Người đầu hàng chờ được giữ sách, sách không quay lại kệ
    assert book.available == 0
    assert active_borrow(member.id, book.id).status == 'pending'
    assert Reservation.query.filter_by(user_id=member.id).one().status == 'fulfilled'
    assert Reservation.query.filter_by(user_id=third.id).one().status == 'waiting'
    assert any('bạn đặt trước đã có' in m for m in notifications_of(member))


def test_hang_cho_bo_qua_nguoi_dang_no_phat(db, member, book_by_title):
    book = book_by_title('Marketing')
    book.quantity = book.available = 1
    db.session.commit()
    holder = make_user(db, 'docgia2')
    clean = make_user(db, 'docgia3')
    borrowing = borrow_book(holder, book.id)
    reserve_book(member, book.id)
    reserve_book(clean, book.id)
    late = active_borrow(member.id, book_by_title('Nhà Giả Kim').id)
    admin_update_borrowing(late.id, 'confirm_return')  # thành viên mẫu bị phạt trả trễ

    admin_update_borrowing(borrowing.id, 'cancel')
    assert active_borrow(clean.id, book.id).status == 'pending'
    assert Reservation.query.filter_by(user_id=member.id, book_id=book.id).one().status == 'waiting'


def test_tang_so_luong_sach_phuc_vu_hang_cho(admin_client, db, member, book_by_title):
    book = book_by_title('Đắc Nhân Tâm')
    book.quantity = 1  # 1 cuốn, đang được mượn (available = 0)
    db.session.commit()
    reserve_book(member, book.id)
    admin_client.post(f'/admin/books/{book.id}/edit', data={'title': book.title, 'quantity': 2})
    # Cuốn mới nhập được giữ ngay cho người đang chờ
    assert active_borrow(member.id, book.id).status == 'pending'
    assert book.available == 0


def test_dang_ky_va_huy_cho_qua_giao_dien(member_client, db, member, book_by_title):
    book = book_by_title('Marketing')
    book.available = 0
    db.session.commit()
    member_client.post(f'/reserve/{book.id}')
    reservation = Reservation.query.filter_by(user_id=member.id, book_id=book.id).one()
    assert 'vị trí thứ 1' in member_client.get(f'/books/{book.id}').get_data(as_text=True)
    member_client.post(f'/reservations/{reservation.id}/cancel')
    assert reservation.status == 'cancelled'


# ---------- Thông báo ----------
def test_nhac_han_tra_khong_gui_trung(member):
    first = send_due_reminders()
    assert first >= 1  # thành viên mẫu có 1 cuốn quá hạn
    assert send_due_reminders() == 0
    assert any('quá hạn trả' in m for m in notifications_of(member))


def test_nhac_sap_den_han(db, member, book_by_title):
    b = active_borrow(member.id, book_by_title('Lập trình Web').id)
    b.due_date = date.today() + timedelta(days=1)
    db.session.commit()
    send_due_reminders(member.id)
    assert any('đến hạn trả ngày' in m for m in notifications_of(member))


def test_trang_thong_bao_va_danh_dau_da_doc(member_client, member):
    send_due_reminders()
    page = member_client.get('/my-books').get_data(as_text=True)
    assert 'chưa đọc' in page
    n = Notification.query.filter_by(user_id=member.id).first()
    res = member_client.post('/notifications/read', data={'id': n.id})
    assert res.headers['Location'].endswith('/my-books')
    assert n.is_read
    member_client.post('/notifications/read')
    assert Notification.query.filter_by(user_id=member.id, is_read=False).count() == 0
    assert member_client.get('/notifications').status_code == 200


def test_thong_bao_khi_tra_tre(member, book_by_title):
    late = active_borrow(member.id, book_by_title('Nhà Giả Kim').id)
    admin_update_borrowing(late.id, 'confirm_return')
    assert any('tiền phạt' in m for m in notifications_of(member))


# ---------- Yêu thích ----------
def test_them_bo_yeu_thich(member_client, member, book_by_title):
    book = book_by_title('Marketing')
    member_client.post(f'/books/{book.id}/favorite')
    assert Favorite.query.filter_by(user_id=member.id, book_id=book.id).count() == 1
    assert book.title in member_client.get('/my-books?tab=favorites').get_data(as_text=True)
    member_client.post(f'/books/{book.id}/favorite')
    assert Favorite.query.filter_by(user_id=member.id).count() == 0


def test_khach_khong_duoc_yeu_thich(client, book_by_title):
    res = client.post(f'/books/{book_by_title("Marketing").id}/favorite')
    assert '/login' in res.headers['Location']


# ---------- Quản trị người dùng ----------
def test_admin_tao_va_sua_nguoi_dung(admin_client):
    admin_client.post('/admin/users/new', data={
        'username': 'sv001', 'password': 'matkhau1', 'full_name': 'Sinh Viên', 'email': 'sv001@test.vn',
        'role': 'member', 'status': 'active'})
    user = User.query.filter_by(username='sv001').one()
    assert user.check_password('matkhau1')
    admin_client.post(f'/admin/users/{user.id}', data={
        'full_name': 'Sinh Viên Mới', 'email': 'sv001@test.vn', 'phone': '0912345678', 'role': 'member', 'status': 'inactive'})
    assert user.full_name == 'Sinh Viên Mới' and user.status == 'inactive'


def test_admin_tao_nguoi_dung_trung_ten(admin_client):
    admin_client.post('/admin/users/new', data={
        'username': 'nguyenvana', 'password': 'matkhau1', 'full_name': 'X', 'email': 'x@test.vn',
        'role': 'member', 'status': 'active'})
    assert any('đã tồn tại' in m for m in flashes())
    assert User.query.filter_by(email='x@test.vn').count() == 0


def test_admin_khong_tu_khoa_minh(admin_client):
    admin = User.query.filter_by(username='admin').one()
    admin_client.post(f'/admin/users/{admin.id}', data={
        'full_name': admin.full_name, 'email': admin.email, 'role': 'member', 'status': 'active'})
    assert admin.role == 'admin'


def test_admin_dat_lai_mat_khau(admin_client, member):
    admin_client.post(f'/admin/users/{member.id}/reset-password', data={'password': 'moi12345'})
    assert member.check_password('moi12345')
    assert any('đặt lại' in m for m in notifications_of(member))


def test_xoa_nguoi_dung(admin_client, db, member, book_by_title):
    admin_client.post(f'/admin/users/{member.id}/delete')  # đang mượn sách -> không xóa được
    assert db.session.get(User, member.id) is not None
    user = make_user(db, 'xoadi')
    db.session.add(Borrowing(user_id=user.id, book_id=book_by_title('Marketing').id, due_date=date.today(),
                             status='returned'))
    db.session.commit()
    admin_client.post(f'/admin/users/{user.id}/delete')
    assert db.session.get(User, user.id) is None
    assert Borrowing.query.filter_by(user_id=user.id).count() == 0


# ---------- Lập phiếu tại quầy ----------
def test_lap_phieu_tai_quay(admin_client, member, book_by_title):
    book = book_by_title('Marketing')
    before = book.available
    admin_client.post('/admin/borrowing/new', data={'reader': 'nguyenvana', 'book': book.isbn})
    b = active_borrow(member.id, book.id)
    assert b.status == 'borrowing' and b.due_date > date.today()
    assert book.available == before - 1


def test_lap_phieu_tai_quay_ap_dung_gioi_han(db, member, book_by_title):
    admin_update_borrowing(active_borrow(member.id, book_by_title('Nhà Giả Kim').id).id, 'confirm_return')
    with pytest.raises(BusinessError, match='khoản phạt'):
        admin_create_borrowing(member.id, book_by_title('Marketing').id)


# ---------- Đánh giá ----------
def test_xoa_danh_gia(db, admin_client, member, book_by_title):
    save_review(member, book_by_title('Lập trình Web').id, 5, 'Hay')
    review = Review.query.filter_by(user_id=member.id).one()
    # Người khác không xóa được
    with pytest.raises(BusinessError):
        delete_review(make_user(db, 'khac'), review.id)
    assert Review.query.count() == 1
    # Quản trị viên xem và xóa được
    assert 'Hay' in admin_client.get('/admin/reviews').get_data(as_text=True)
    admin_client.post(f'/reviews/{review.id}/delete')
    assert Review.query.count() == 0


def test_nguoi_viet_tu_xoa_danh_gia(member_client, member, book_by_title):
    save_review(member, book_by_title('Lập trình Web').id, 4, 'Ổn')
    member_client.post(f'/reviews/{Review.query.one().id}/delete')
    assert Review.query.count() == 0


def test_trang_quan_tri_moi_hien_thi(admin_client, member, book_by_title):
    book = book_by_title('Đắc Nhân Tâm')
    book.quantity = 1
    reserve_book(member, book.id)
    for url in ('/admin/reservations', '/admin/reviews', '/admin/users/new', f'/admin/users/{member.id}',
                f'/admin/users/{member.id}?edit=1', '/admin/borrowing'):
        assert admin_client.get(url).status_code == 200, url
