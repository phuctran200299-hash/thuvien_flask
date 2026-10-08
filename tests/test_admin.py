"""Kiểm thử trang quản trị: người dùng, danh mục, cài đặt, xuất báo cáo, CSRF."""
from app import create_app
from app.models import Category, Setting, User
from conftest import flashes


def test_admin_khong_tu_khoa_hoac_tu_ha_quyen(admin_client):
    admin = User.query.filter_by(username='admin').one()
    admin_client.post('/admin/users', data={'user_id': admin.id, 'field': 'status', 'value': 'banned'})
    admin_client.post('/admin/users', data={'user_id': admin.id, 'field': 'role', 'value': 'member'})
    assert admin.status == 'active' and admin.role == 'admin'


def test_gia_tri_vai_tro_khong_hop_le(admin_client, member):
    admin_client.post('/admin/users', data={'user_id': member.id, 'field': 'role', 'value': 'superadmin'})
    assert member.role == 'member'
    assert flashes(admin_client) == ['Giá trị không hợp lệ']


def test_crud_danh_muc(admin_client):
    admin_client.post('/admin/categories', data={'name': 'Giáo trình', 'description': 'Nội bộ'})
    assert Category.query.filter_by(name='Giáo trình').count() == 1
    admin_client.post('/admin/categories', data={'name': 'Văn học'})
    assert 'đã tồn tại' in flashes(admin_client)[-1]
    used = Category.query.filter_by(name='Văn học').one()
    admin_client.post('/admin/categories', data={'action': 'delete', 'id': used.id})
    assert Category.query.get(used.id) is not None  # còn tài liệu nên không xóa được
    empty = Category.query.filter_by(name='Giáo trình').one()
    admin_client.post('/admin/categories', data={'action': 'delete', 'id': empty.id})
    assert Category.query.filter_by(name='Giáo trình').count() == 0


def test_cai_dat_kiem_tra_du_lieu(admin_client):
    admin_client.post('/admin/settings', data={'fine_per_day': 'abc', 'contact_email': 'sai-email'})
    message = flashes(admin_client)[0]
    assert 'số nguyên' in message and 'không hợp lệ' in message
    assert Setting.query.filter_by(key='fine_per_day').one().value == '5000'
    admin_client.post('/admin/settings', data={'fine_per_day': '3000'})
    assert Setting.query.filter_by(key='fine_per_day').one().value == '3000'


def test_xuat_csv_co_bom_va_chong_cong_thuc(admin_client, db):
    admin = User.query.filter_by(username='admin').one()
    admin.full_name = '=HYPERLINK("http://evil")'
    db.session.commit()
    res = admin_client.get('/admin/export/users')
    text = res.data.decode('utf-8')
    assert res.mimetype == 'text/csv' and text.startswith('﻿')
    assert "'=HYPERLINK" in text


def test_csrf_bat_buoc_voi_post(tmp_path):
    from app.config import TestConfig

    class CsrfConfig(TestConfig):
        WTF_CSRF_ENABLED = True
        DOCUMENT_FOLDER = tmp_path

    app = create_app(CsrfConfig)
    with app.app_context():
        from app.extensions import db
        db.create_all()
        res = app.test_client().post('/login', data={'username': 'admin', 'password': 'password123'})
        assert res.status_code == 400
        db.drop_all()


def test_trang_thong_ke_va_dashboard(admin_client):
    for path in ('/admin/', '/admin/statistics', '/admin/access-logs', '/admin/borrowing?status=overdue'):
        assert admin_client.get(path).status_code == 200
