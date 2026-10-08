"""Kiểm thử đăng nhập, đăng ký, phân quyền."""
from app.models import User
from conftest import flashes


def test_dang_nhap_thanh_cong(client):
    res = client.post('/login', data={'username': 'admin', 'password': 'password123'})
    assert res.status_code == 302
    assert client.get('/admin/').status_code == 200


def test_dang_nhap_bang_email(client):
    client.post('/login', data={'username': 'nguyenvana@gmail.com', 'password': 'password123'})
    assert client.get('/my-books').status_code == 200


def test_dang_nhap_sai_khong_lo_tai_khoan_ton_tai(client):
    client.post('/login', data={'username': 'admin', 'password': 'sai'})
    sai_mat_khau = flashes(client)
    client.post('/login', data={'username': 'khong-ton-tai', 'password': 'sai'})
    sai_tai_khoan = flashes(client)
    assert sai_mat_khau == sai_tai_khoan == ['Tên đăng nhập hoặc mật khẩu không chính xác']


def test_tai_khoan_bi_khoa_khong_dang_nhap_duoc(client, db, member):
    member.status = 'banned'
    db.session.commit()
    client.post('/login', data={'username': 'nguyenvana', 'password': 'password123'})
    assert 'đã bị khóa' in flashes(client)[0]
    assert client.get('/my-books').status_code == 302


def test_khoa_tai_khoan_dang_dang_nhap_bi_dang_xuat_ngay(member_client, db, member):
    assert member_client.get('/my-books').status_code == 200
    member.status = 'banned'
    db.session.commit()
    assert member_client.get('/my-books').status_code == 302


def test_dang_ky_hop_le(client, db):
    res = client.post('/register', data={'username': 'sinhvien01', 'full_name': 'Trần Văn B', 'email': 'b@vui.edu.vn',
                                         'password': '123456', 'confirm_password': '123456'})
    assert res.status_code == 302
    user = User.query.filter_by(username='sinhvien01').one()
    assert user.role == 'member' and user.check_password('123456')
    assert user.password_hash != '123456'  # mật khẩu được băm


def test_dang_ky_trung_va_du_lieu_sai(client):
    client.post('/register', data={'username': 'admin', 'full_name': '', 'email': 'admin@library.com',
                                   'password': '123', 'confirm_password': '456'})
    errors = flashes(client)[0]
    for text in ('Tên đăng nhập đã tồn tại', 'Email đã được sử dụng', 'Họ tên không được để trống',
                 'ít nhất 6 ký tự', 'không khớp'):
        assert text in errors


def test_thanh_vien_khong_vao_duoc_trang_quan_tri(member_client):
    assert member_client.get('/admin/').status_code == 403
    assert member_client.get('/admin/books').status_code == 403


def test_khach_bi_chuyen_ve_dang_nhap(client):
    res = client.get('/my-books')
    assert res.status_code == 302 and '/login' in res.headers['Location']


def test_open_redirect_bi_chan(client):
    res = client.post('/login?next=https://evil.example.com', data={'username': 'admin', 'password': 'password123'})
    assert res.headers['Location'] == '/'


def test_dang_xuat_phai_dung_post(member_client):
    assert member_client.get('/logout').status_code == 405
    member_client.post('/logout')
    assert member_client.get('/my-books').status_code == 302
