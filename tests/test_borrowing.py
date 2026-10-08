"""Kiểm thử nghiệp vụ mượn - trả, gia hạn, tiền phạt."""
from datetime import date, datetime, timedelta

import pytest

from app.models import Borrowing, Setting
from app.services import (BusinessError, admin_update_borrowing, borrow_book, calculate_fine, cancel_by_user,
                          expire_pending_borrowings, renew_borrowing)
from conftest import active_borrow, flashes


def set_setting(db, key, value):
    Setting.query.filter_by(key=key).one().value = str(value)
    db.session.commit()


def test_dat_muon_giam_so_luong_con_lai(member_client, member, book_by_title):
    book = book_by_title('Marketing')
    before = book.available
    res = member_client.post(f'/borrow/{book.id}')
    assert res.status_code == 302
    assert book.available == before - 1
    assert active_borrow(member.id, book.id).status == 'pending'


def test_khong_dat_trung_sach_dang_cho(member, book_by_title):
    book = book_by_title('Marketing')
    borrow_book(member, book.id)
    with pytest.raises(BusinessError, match='đã đặt hoặc đang mượn'):
        borrow_book(member, book.id)


def test_khong_muon_sach_da_het(member, book_by_title):
    with pytest.raises(BusinessError, match='không còn sẵn'):
        borrow_book(member, book_by_title('Đắc Nhân Tâm').id)


def test_gioi_han_so_sach_moi_nguoi(db, member, book_by_title):
    set_setting(db, 'max_books_per_user', 2)  # thành viên mẫu đang mượn sẵn 2 cuốn
    with pytest.raises(BusinessError, match='tối đa 2 cuốn'):
        borrow_book(member, book_by_title('Marketing').id)


def test_con_no_phat_thi_khong_duoc_muon(db, member, book_by_title):
    late = active_borrow(member.id, book_by_title('Nhà Giả Kim').id)
    admin_update_borrowing(late.id, 'confirm_return')
    with pytest.raises(BusinessError, match='khoản phạt chưa thanh toán'):
        borrow_book(member, book_by_title('Marketing').id)
    admin_update_borrowing(late.id, 'mark_paid')
    assert borrow_book(member, book_by_title('Marketing').id).status == 'pending'


def test_tu_huy_phieu_cho(member, book_by_title):
    book = book_by_title('Marketing')
    borrowing = borrow_book(member, book.id)
    cancel_by_user(member, borrowing.id)
    assert borrowing.status == 'cancelled'
    assert book.available == book.quantity


def test_xac_nhan_lay_sach_tinh_lai_han_tra(db, member, book_by_title):
    set_setting(db, 'max_borrow_days', 10)
    borrowing = borrow_book(member, book_by_title('Marketing').id)
    borrowing.borrow_date = date.today() - timedelta(days=2)  # giả sử đặt từ 2 ngày trước
    db.session.commit()
    admin_update_borrowing(borrowing.id, 'confirm_pickup')
    assert borrowing.status == 'borrowing'
    assert borrowing.borrow_date == date.today()
    assert borrowing.due_date == date.today() + timedelta(days=10)


def test_gia_han_toi_da_va_luu_lich_su(member, book_by_title):
    borrowing = active_borrow(member.id, book_by_title('Lập trình').id)
    due = borrowing.due_date
    renew_borrowing(member, borrowing.id)
    renew_borrowing(member, borrowing.id)
    assert borrowing.due_date == due + timedelta(days=14)
    assert [r.old_due_date for r in borrowing.renewals] == [due, due + timedelta(days=7)]
    with pytest.raises(BusinessError, match='tối đa 2 lần'):
        renew_borrowing(member, borrowing.id)


def test_khong_gia_han_sach_qua_han(member, book_by_title):
    late = active_borrow(member.id, book_by_title('Nhà Giả Kim').id)
    with pytest.raises(BusinessError, match='quá hạn'):
        renew_borrowing(member, late.id)


def test_tra_tre_tinh_tien_phat(member, book_by_title):
    book = book_by_title('Nhà Giả Kim')
    late = active_borrow(member.id, book.id)  # dữ liệu mẫu: trễ 6 ngày
    message = admin_update_borrowing(late.id, 'confirm_return')
    assert late.status == 'returned' and late.return_date == date.today()
    assert late.fine_amount == 6 * 5000 and not late.fine_paid
    assert '30.000đ' in message
    assert book.available == 5


def test_tra_dung_han_khong_phat(member, book_by_title):
    borrowing = active_borrow(member.id, book_by_title('Lập trình').id)
    admin_update_borrowing(borrowing.id, 'confirm_return')
    assert borrowing.fine_amount == 0 and borrowing.fine_paid


def test_phi_phat_lay_tu_cai_dat(db):
    set_setting(db, 'fine_per_day', 2000)
    assert calculate_fine(date.today() - timedelta(days=3)) == 6000
    assert calculate_fine(date.today() + timedelta(days=3)) == 0


def test_tu_dong_huy_phieu_cho_qua_han_giu_sach(db, member, book_by_title):
    book = book_by_title('Marketing')
    borrowing = borrow_book(member, book.id)
    borrowing.created_at = datetime.now() - timedelta(days=5)
    db.session.commit()
    assert expire_pending_borrowings() == 1
    assert borrowing.status == 'cancelled'
    assert book.available == book.quantity


def test_trang_thai_khong_hop_le(member, book_by_title):
    returned = Borrowing.query.filter_by(user_id=member.id, status='returned').first()
    with pytest.raises(BusinessError):
        admin_update_borrowing(returned.id, 'confirm_return')
    with pytest.raises(BusinessError):
        admin_update_borrowing(returned.id, 'cancel')


def test_nguoi_khac_khong_huy_duoc_phieu_cua_minh(app, db, member, book_by_title):
    from app.models import User
    other = User(username='nguoikhac', full_name='Người khác', email='k@x.vn')
    other.set_password('123456')
    db.session.add(other)
    db.session.commit()
    borrowing = borrow_book(member, book_by_title('Marketing').id)
    with pytest.raises(BusinessError):
        cancel_by_user(other, borrowing.id)


def test_admin_xu_ly_phieu_qua_giao_dien(admin_client, member, book_by_title):
    late = active_borrow(member.id, book_by_title('Nhà Giả Kim').id)
    admin_client.post(f'/admin/borrowing/{late.id}/confirm_return')
    assert 'tiền phạt: 30.000đ' in flashes(admin_client)[0]
    assert admin_client.get('/admin/borrowing?status=unpaid').status_code == 200
