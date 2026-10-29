"""Kiểm thử lệnh bổ sung dữ liệu demo (flask seed-demo)."""
from sqlalchemy import func, select

from app.models import Book, Borrowing, Reservation, User
from app.seed_demo import BOOKS, MEMBERS, seed_demo_data


def test_bo_sung_du_lieu_va_hop_le(app, db):
    books_before = Book.query.count()
    added = seed_demo_data()
    assert added['books'] == len(BOOKS) and added['members'] == len(MEMBERS)
    assert Book.query.count() == books_before + len(BOOKS)
    assert Borrowing.query.filter_by(status='returned').count() > 50
    assert Reservation.query.filter_by(status='waiting').count() == 3
    # Số bản còn lại luôn = tổng số - số phiếu đang mượn/chờ lấy, không âm
    active = dict(db.session.execute(select(Borrowing.book_id, func.count(Borrowing.id))
                                     .where(Borrowing.status.in_(('pending', 'borrowing')))
                                     .group_by(Borrowing.book_id)).all())
    for b in Book.query.all():
        assert b.available == b.quantity - active.get(b.id, 0) >= 0
    # Không ai mượn trùng một sách cùng lúc
    dup = db.session.execute(select(Borrowing.user_id, Borrowing.book_id, func.count())
                             .where(Borrowing.status.in_(('pending', 'borrowing')))
                             .group_by(Borrowing.user_id, Borrowing.book_id).having(func.count() > 1)).all()
    assert dup == []


def test_chay_lai_khong_trung(app, db):
    seed_demo_data()
    counts = (Book.query.count(), User.query.count(), Borrowing.query.count())
    assert seed_demo_data() == {'categories': 0, 'books': 0, 'files': 0, 'members': 0}
    assert (Book.query.count(), User.query.count(), Borrowing.query.count()) == counts


def test_cac_trang_hien_thi_voi_du_lieu_lon(app, admin_client):
    seed_demo_data()
    for url in ('/admin/', '/admin/books?page=2', '/admin/borrowing', '/admin/statistics', '/admin/access-logs?page=3',
                '/admin/reservations', '/admin/reviews', '/books?page=2', '/'):
        assert admin_client.get(url).status_code == 200, url
