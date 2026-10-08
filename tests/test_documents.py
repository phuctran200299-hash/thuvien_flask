"""Kiểm thử tài liệu số: phân quyền đọc/tải, lịch sử truy cập, upload, tìm kiếm, đánh giá."""
import io

from app.models import AccessLog, Book, DocumentFile, Review
from conftest import flashes


def file_of(book_title):
    return DocumentFile.query.join(Book).filter(Book.title.like(f'{book_title}%')).first()


def test_khach_doc_duoc_tai_lieu_cong_khai(client):
    doc = file_of('Sapiens')
    res = client.get(f'/document/{doc.id}')
    assert res.status_code == 200 and res.mimetype == 'application/pdf'
    assert res.data.startswith(b'%PDF')


def test_khach_khong_doc_duoc_tai_lieu_thanh_vien(client):
    doc = file_of('Nhà Giả Kim')
    res = client.get(f'/read/{doc.id}')
    assert res.status_code == 302 and '/login' in res.headers['Location']
    assert client.get(f'/document/{doc.id}').status_code == 302


def test_tai_lieu_chi_doc_khong_cho_tai(member_client):
    doc = file_of('Nhà Giả Kim')
    assert member_client.get(f'/read/{doc.id}').status_code == 200
    res = member_client.get(f'/document/{doc.id}?download=1')
    assert res.status_code == 302
    assert 'chỉ cho phép đọc trực tuyến' in flashes(member_client)[0]


def test_admin_van_tai_duoc_tai_lieu_chi_doc(admin_client):
    doc = file_of('Nhà Giả Kim')
    res = admin_client.get(f'/document/{doc.id}?download=1')
    assert res.status_code == 200 and 'attachment' in res.headers['Content-Disposition']


def test_ghi_lich_su_doc_va_tai(member_client, member):
    doc = file_of('Lập trình')
    before = AccessLog.query.filter_by(user_id=member.id).count()
    member_client.get(f'/read/{doc.id}')
    member_client.get(f'/document/{doc.id}?download=1')
    logs = AccessLog.query.filter_by(user_id=member.id).order_by(AccessLog.id.desc()).limit(2).all()
    assert AccessLog.query.filter_by(user_id=member.id).count() == before + 2
    assert {log.action for log in logs} == {'read', 'download'}


def test_luot_xem_chi_tinh_mot_lan_moi_phien(client, book_by_title):
    book = book_by_title('Marketing')
    client.get(f'/books/{book.id}')
    client.get(f'/books/{book.id}')
    assert book.view_count == 1


def test_tim_kiem_theo_tac_gia_va_nam(client):
    html = client.get('/books?search=Harari').get_data(as_text=True)
    assert 'Sapiens' in html and 'Marketing 5.0' not in html
    html = client.get('/books?year_from=2022').get_data(as_text=True)
    assert 'Marketing 5.0' in html and 'Nhà Giả Kim' not in html
    html = client.get('/books?digital=1').get_data(as_text=True)
    assert 'Sapiens' in html and 'Marketing 5.0' not in html


def _upload(admin_client, files, **fields):
    data = {'title': 'Cấu trúc dữ liệu và giải thuật', 'author_name': 'Tác Giả Mới', 'publisher_name': 'NXB Bách Khoa',
            'publish_year': '2024', 'quantity': '3', 'access_level': 'member', 'allow_download': '1', **fields,
            'documents': files}
    return admin_client.post('/admin/books/new', data=data, content_type='multipart/form-data')


def test_them_tai_lieu_kem_tep_va_tu_tao_tac_gia(admin_client, db):
    _upload(admin_client, [(io.BytesIO(b'%PDF-1.4 noi dung'), 'giáo-trình.pdf')])
    book = Book.query.filter_by(title='Cấu trúc dữ liệu và giải thuật').one()
    assert book.author.name == 'Tác Giả Mới' and book.available == 3
    assert len(book.files) == 1 and book.files[0].mime_type == 'application/pdf'
    assert book.files[0].original_name == 'giáo-trình.pdf'


def test_tu_choi_file_gia_mao(admin_client):
    _upload(admin_client, [(io.BytesIO(b'<?php system($_GET["c"]); ?>' + b'\x00' * 10), 'shell.pdf')])
    book = Book.query.filter_by(title='Cấu trúc dữ liệu và giải thuật').one()
    assert book.files == []
    assert 'không được hỗ trợ' in flashes(admin_client)[0]


def test_khong_giam_so_luong_duoi_so_dang_muon(admin_client, book_by_title):
    book = book_by_title('Lập trình')  # đang có 1 cuốn được mượn
    admin_client.post(f'/admin/books/{book.id}/edit', data={'title': book.title, 'quantity': '0'})
    assert 'không được nhỏ hơn' in flashes(admin_client)[0]
    assert book.quantity == 12


def test_xoa_tep_giu_lai_lich_su_truy_cap(admin_client, db):
    doc = file_of('Lập trình')
    logs = AccessLog.query.filter_by(file_id=doc.id).count()
    assert logs > 0
    admin_client.post(f'/admin/files/{doc.id}/delete')
    assert db.session.get(DocumentFile, doc.id) is None
    assert AccessLog.query.filter_by(file_id=None, action='download').count() >= 1


def test_danh_gia_chi_khi_da_muon_hoac_doc(member_client, member, book_by_title):
    marketing, web = book_by_title('Marketing'), book_by_title('Lập trình')
    member_client.post(f'/books/{marketing.id}/review', data={'rating': 5})  # đã mượn và trả
    member_client.post(f'/books/{web.id}/review', data={'rating': 4, 'comment': '<script>alert(1)</script>'})
    assert Review.query.count() == 2
    html = member_client.get(f'/books/{web.id}').get_data(as_text=True)
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html and '<script>alert(1)' not in html


def test_chua_muon_chua_doc_khong_duoc_danh_gia(admin_client, book_by_title):
    admin_client.post(f'/books/{book_by_title("Đắc Nhân Tâm").id}/review', data={'rating': 5})
    assert Review.query.count() == 0
