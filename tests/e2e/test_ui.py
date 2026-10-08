"""Kiểm thử giao diện end-to-end bằng Playwright (trình duyệt Chromium thật).

Chạy:  pytest -m e2e            (thêm --headed để xem trình duyệt thao tác)
Cần cài trình duyệt một lần:  python -m playwright install chromium
"""
import re
import threading

import pytest
from playwright.sync_api import Page, expect
from werkzeug.serving import make_server

pytestmark = pytest.mark.e2e


@pytest.fixture()
def live_server(app):
    """Chạy ứng dụng thật trên một cổng ngẫu nhiên trong luồng nền."""
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()


def login(page: Page, base, username):
    page.goto(f'{base}/login')
    page.get_by_label('Tên đăng nhập hoặc email').fill(username)
    page.get_by_label('Mật khẩu').fill('password123')
    page.get_by_role('button', name='Đăng nhập').click()
    expect(page.locator('.toast')).to_contain_text('Đăng nhập thành công')


def test_khach_tim_kiem_va_doc_tai_lieu_cong_khai(page: Page, live_server):
    page.goto(live_server)
    page.get_by_placeholder('Tên tài liệu, tác giả, từ khóa...').fill('Harari')
    page.get_by_role('button', name='Tìm kiếm').click()
    expect(page.get_by_text('Tìm thấy')).to_contain_text('1 kết quả')
    page.get_by_role('link', name=re.compile('Sapiens')).first.click()
    page.get_by_role('link', name='Đọc trực tuyến').click()
    expect(page).to_have_url(re.compile(r'/read/\d+'))
    expect(page.locator('iframe')).to_be_visible()


def test_khach_bi_yeu_cau_dang_nhap_voi_tai_lieu_thanh_vien(page: Page, live_server):
    page.goto(f'{live_server}/books?search=Nhà Giả Kim')
    page.get_by_role('link', name=re.compile('Nhà Giả Kim')).first.click()
    expect(page.get_by_role('link', name='🔒 Đăng nhập để đọc')).to_be_visible()


def test_thanh_vien_dat_muon_va_thu_thu_xac_nhan(page: Page, browser, live_server):
    login(page, live_server, 'nguyenvana')
    page.goto(f'{live_server}/books?search=Marketing')
    page.get_by_role('link', name=re.compile('Marketing 5.0')).first.click()
    page.once('dialog', lambda dialog: dialog.accept())
    page.get_by_role('button', name='Đặt mượn sách').click()
    expect(page.get_by_text('Đặt mượn thành công!')).to_be_visible()
    expect(page.get_by_text('Chờ lấy sách').first).to_be_visible()

    # Thủ thư xác nhận người dùng đã đến lấy sách (phiên trình duyệt riêng)
    admin = browser.new_context().new_page()
    login(admin, live_server, 'admin')
    admin.goto(f'{live_server}/admin/borrowing?status=pending')
    admin.once('dialog', lambda dialog: dialog.accept())
    admin.get_by_role('button', name='Xác nhận đã lấy').click()
    expect(admin.locator('.toast')).to_contain_text('Đã xác nhận người dùng lấy sách')

    page.reload()
    expect(page.get_by_role('button', name='Gia hạn (0/2)').first).to_be_visible()


def test_thong_bao_khong_bi_chen_ma_doc(page: Page, live_server):
    """Họ tên chứa mã HTML không được thực thi khi hiển thị trong thông báo toast."""
    page.goto(f'{live_server}/register')
    page.get_by_label('Họ và tên *').fill('<img src=x onerror="window.__xss=1">')
    page.get_by_label('Tên đăng nhập *').fill('hacker01')
    page.get_by_label('Email *').fill('h@x.vn')
    page.get_by_label('Mật khẩu * (tối thiểu 6 ký tự)').fill('123456')
    page.get_by_label('Xác nhận mật khẩu *').fill('123456')
    page.get_by_role('button', name='Đăng ký').click()
    page.get_by_label('Tên đăng nhập hoặc email').fill('hacker01')
    page.get_by_label('Mật khẩu').fill('123456')
    page.get_by_role('button', name='Đăng nhập').click()
    expect(page.locator('.toast')).to_contain_text('<img src=x')
    assert page.evaluate('window.__xss') is None


def test_admin_xem_thong_ke_co_bieu_do(page: Page, live_server):
    login(page, live_server, 'admin')
    page.goto(f'{live_server}/admin/statistics')
    expect(page.locator('#chart-monthly')).to_be_visible()
    expect(page.locator('#chart-access')).to_be_visible()
