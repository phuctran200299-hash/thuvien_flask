"""Dữ liệu demo phong phú cho hệ thống (lệnh `flask seed-demo`).

Bổ sung vào dữ liệu đang có, không xóa gì: thêm danh mục, khoảng 40 đầu sách (một phần có bản số PDF),
10 sinh viên, lịch sử mượn trả 12 tháng, phiếu đang mượn/quá hạn/chờ lấy, hàng chờ đặt trước, đánh giá,
lượt truy cập 60 ngày và thông báo. Chạy lại nhiều lần không bị trùng (bỏ qua sách/người dùng đã có).
"""
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy import func, select

from .extensions import db
from .models import (AccessLog, Author, Book, Borrowing, BorrowRenewal, Category, DocumentFile, Favorite,
                     Notification, Publisher, Reservation, Review, User)

IMG = 'https://images.unsplash.com/photo-{}?w=400&h=600&fit=crop'
COVERS = ['1543002588-bfa74002ed7e', '1532012197267-da84d127e765', '1497633762265-9d179a990aa6',
          '1512820790803-83ca734da794', '1544947950-fa07a98d237f', '1516979187457-637abb4f9353',
          '1544716278-ca5e3f4abd8c', '1589998059171-988d887df646', '1507842217343-583bb7270b66',
          '1495446815901-a7297e633e8d', '1481627834876-b7833e8f5570', '1519682337058-a94d519337bc',
          '1456513080510-7bf3a84b82f8', '1474932430478-367dbb6832c1']

NEW_CATEGORIES = [('Ngoại ngữ', 'Sách học tiếng Anh, từ điển'), ('Lịch sử', 'Sách lịch sử Việt Nam và thế giới'),
                  ('Thiếu nhi', 'Sách dành cho thiếu nhi')]

# (tên, tác giả, NXB, danh mục, năm, từ khóa, số bản, có bản số, mô tả)
BOOKS = [
    ('Cấu trúc dữ liệu và giải thuật', 'Trần Thị Hoa', 'NXB Giáo dục Việt Nam', 'Công nghệ thông tin', 2021,
     'thuật toán, cấu trúc dữ liệu, lập trình', 10, True, 'Giáo trình về mảng, danh sách liên kết, cây, đồ thị và các thuật toán sắp xếp, tìm kiếm.'),
    ('Hệ quản trị cơ sở dữ liệu SQL Server', 'Phạm Minh Tuấn', 'NXB Thông tin và Truyền thông', 'Công nghệ thông tin', 2022,
     'sql server, cơ sở dữ liệu, truy vấn', 8, True, 'Thiết kế cơ sở dữ liệu, viết truy vấn T-SQL, thủ tục, trigger và tối ưu chỉ mục.'),
    ('Mạng máy tính căn bản', 'Nguyễn Văn An', 'NXB Giáo dục Việt Nam', 'Công nghệ thông tin', 2020,
     'mạng, tcp/ip, giao thức', 6, False, 'Mô hình OSI, TCP/IP, định tuyến, chuyển mạch và cấu hình mạng cơ bản.'),
    ('Kiểm thử phần mềm', 'Lê Thị Mai', 'NXB Khoa học và Kỹ thuật', 'Công nghệ thông tin', 2023,
     'kiểm thử, pytest, chất lượng phần mềm', 5, True, 'Các mức kiểm thử, thiết kế ca kiểm thử, kiểm thử tự động.'),
    ('Clean Code', 'Robert C. Martin', 'NXB Lao động', 'Công nghệ thông tin', 2019,
     'clean code, lập trình, bảo trì phần mềm', 4, False, 'Nguyên tắc viết mã nguồn sạch, dễ đọc, dễ bảo trì.'),
    ('Nhập môn trí tuệ nhân tạo', 'Phạm Minh Tuấn', 'NXB Khoa học và Kỹ thuật', 'Công nghệ thông tin', 2024,
     'trí tuệ nhân tạo, ai, học máy', 6, True, 'Tìm kiếm, biểu diễn tri thức, học máy và các ứng dụng AI.'),
    ('Lập trình Python cơ bản', 'Nguyễn Văn An', 'NXB Thông tin và Truyền thông', 'Công nghệ thông tin', 2023,
     'python, lập trình, nhập môn', 12, True, 'Cú pháp Python, cấu trúc điều khiển, hàm, xử lý tệp và lập trình hướng đối tượng.'),
    ('An toàn và bảo mật thông tin', 'Trần Thị Hoa', 'NXB Thông tin và Truyền thông', 'Công nghệ thông tin', 2022,
     'bảo mật, an toàn thông tin, mã hóa', 5, False, 'Mã hóa, xác thực, các lỗ hổng ứng dụng web và biện pháp phòng chống.'),
    ('Phân tích và thiết kế hệ thống thông tin', 'Lê Thị Mai', 'NXB Giáo dục Việt Nam', 'Công nghệ thông tin', 2021,
     'phân tích thiết kế, uml, hệ thống thông tin', 7, True, 'Khảo sát, phân tích yêu cầu, mô hình hóa UML và thiết kế hệ thống.'),
    ('Lập trình JavaScript hiện đại', 'Phạm Minh Tuấn', 'NXB Thông tin và Truyền thông', 'Công nghệ thông tin', 2024,
     'javascript, web, frontend', 6, False, 'JavaScript ES6+, DOM, xử lý bất đồng bộ và xây dựng giao diện web.'),
    ('Kinh tế học vi mô', 'Trần Thị Hoa', 'NXB Lao động', 'Kinh tế - Quản lý', 2020,
     'kinh tế học, cung cầu, thị trường', 8, True, 'Cung cầu, hành vi người tiêu dùng, doanh nghiệp và cấu trúc thị trường.'),
    ('Marketing căn bản', 'Lê Thị Mai', 'NXB Lao động', 'Kinh tế - Quản lý', 2021,
     'marketing, thị trường, khách hàng', 6, False, 'Nghiên cứu thị trường, hành vi khách hàng và chiến lược marketing hỗn hợp.'),
    ('Cha giàu cha nghèo', 'Robert Kiyosaki', 'NXB Trẻ', 'Kinh tế - Quản lý', 2018,
     'tài chính cá nhân, đầu tư', 5, False, 'Quan niệm về tiền bạc, tài sản và đầu tư cá nhân.'),
    ('Nghĩ giàu và làm giàu', 'Napoleon Hill', 'NXB Tổng hợp', 'Kinh tế - Quản lý', 2017,
     'thành công, tư duy, làm giàu', 4, False, 'Các nguyên tắc tư duy dẫn tới thành công.'),
    ('Truyện Kiều', 'Nguyễn Du', 'NXB Văn học', 'Văn học', 2017,
     'thơ, văn học cổ điển, truyện thơ nôm', 6, True, 'Kiệt tác truyện thơ Nôm của văn học Việt Nam.'),
    ('Dế Mèn phiêu lưu ký', 'Tô Hoài', 'NXB Kim Đồng', 'Thiếu nhi', 2019,
     'thiếu nhi, phiêu lưu, văn học Việt Nam', 8, True, 'Cuộc phiêu lưu của chú Dế Mèn qua thế giới loài vật.'),
    ('Số đỏ', 'Vũ Trọng Phụng', 'NXB Văn học', 'Văn học', 2016,
     'tiểu thuyết, trào phúng, văn học Việt Nam', 4, True, 'Tiểu thuyết trào phúng về xã hội thành thị thời kỳ trước 1945.'),
    ('Tắt đèn', 'Ngô Tất Tố', 'NXB Văn học', 'Văn học', 2016,
     'tiểu thuyết, hiện thực, văn học Việt Nam', 4, True, 'Tiểu thuyết hiện thực về cuộc sống người nông dân.'),
    ('Tôi thấy hoa vàng trên cỏ xanh', 'Nguyễn Nhật Ánh', 'NXB Trẻ', 'Văn học', 2018,
     'tuổi thơ, truyện dài, văn học Việt Nam', 6, False, 'Câu chuyện tuổi thơ ở một làng quê miền Trung.'),
    ('Mắt biếc', 'Nguyễn Nhật Ánh', 'NXB Trẻ', 'Văn học', 2019,
     'tình cảm, truyện dài, văn học Việt Nam', 2, False, 'Câu chuyện tình cảm nhẹ nhàng, sâu lắng.'),
    ('Hoàng tử bé', 'Antoine de Saint-Exupéry', 'NXB Hội Nhà văn', 'Thiếu nhi', 2019,
     'thiếu nhi, triết lý, văn học nước ngoài', 5, True, 'Câu chuyện về hoàng tử nhỏ đến từ một tiểu tinh cầu.'),
    ('Những người khốn khổ', 'Victor Hugo', 'NXB Văn học', 'Văn học', 2020,
     'tiểu thuyết, văn học Pháp, kinh điển', 3, False, 'Tiểu thuyết kinh điển của văn học Pháp.'),
    ('Đời ngắn đừng ngủ dài', 'Robin Sharma', 'NXB Trẻ', 'Kỹ năng sống', 2018,
     'kỹ năng sống, phát triển bản thân', 5, False, 'Những lời khuyên ngắn gọn về sống có mục tiêu.'),
    ('Kỹ năng thuyết trình', 'Lê Thị Mai', 'NXB Tổng hợp', 'Kỹ năng sống', 2020,
     'kỹ năng, giao tiếp, thuyết trình', 8, True, 'Chuẩn bị nội dung, thiết kế slide và trình bày trước đám đông.'),
    ('Tư duy nhanh và chậm', 'Daniel Kahneman', 'NXB Thế giới', 'Tâm lý - Tư duy', 2021,
     'tâm lý, tư duy, ra quyết định', 4, False, 'Hai hệ thống tư duy và các thiên kiến khi ra quyết định.'),
    ('Homo Deus: Lược sử tương lai', 'Yuval Noah Harari', 'NXB Thế giới', 'Khoa học - Công nghệ', 2020,
     'tương lai, công nghệ, nhân loại', 4, False, 'Những thách thức của nhân loại trong thế kỷ 21.'),
    ('21 bài học cho thế kỷ 21', 'Yuval Noah Harari', 'NXB Thế giới', 'Khoa học - Công nghệ', 2021,
     'xã hội, công nghệ, thế kỷ 21', 4, False, 'Các vấn đề lớn của thế giới hiện đại.'),
    ('Lược sử thời gian', 'Stephen Hawking', 'NXB Trẻ', 'Khoa học - Công nghệ', 2018,
     'vũ trụ, vật lý, thiên văn', 3, True, 'Giới thiệu về vũ trụ, lỗ đen và thời gian.'),
    ('Vũ trụ', 'Carl Sagan', 'NXB Thế giới', 'Khoa học - Công nghệ', 2019,
     'vũ trụ, thiên văn, khoa học', 3, False, 'Hành trình khám phá vũ trụ và lịch sử khoa học.'),
    ('English Grammar in Use', 'Raymond Murphy', 'NXB Tổng hợp', 'Ngoại ngữ', 2019,
     'tiếng anh, ngữ pháp, english', 10, True, 'Sách ngữ pháp tiếng Anh trình độ trung cấp kèm bài tập.'),
    ('Từ điển Anh - Việt', 'Trần Thị Hoa', 'NXB Giáo dục Việt Nam', 'Ngoại ngữ', 2020,
     'từ điển, tiếng anh, từ vựng', 6, False, 'Từ điển Anh - Việt thông dụng cho học sinh, sinh viên.'),
    ('Luyện thi TOEIC 750+', 'Lê Thị Mai', 'NXB Tổng hợp', 'Ngoại ngữ', 2023,
     'toeic, tiếng anh, luyện thi', 8, True, 'Chiến lược làm bài và đề luyện tập TOEIC.'),
    ('Việt Nam sử lược', 'Trần Trọng Kim', 'NXB Văn học', 'Lịch sử', 2018,
     'lịch sử việt nam, sử học', 4, True, 'Bộ sử khái quát lịch sử Việt Nam.'),
    ('Đại Việt sử ký toàn thư', 'Ngô Sĩ Liên', 'NXB Văn học', 'Lịch sử', 2017,
     'lịch sử việt nam, sử học, cổ sử', 2, False, 'Bộ quốc sử của Việt Nam thời phong kiến.'),
    ('Lịch sử thế giới cận đại', 'Phạm Minh Tuấn', 'NXB Giáo dục Việt Nam', 'Lịch sử', 2021,
     'lịch sử thế giới, cận đại', 5, False, 'Các sự kiện lớn của lịch sử thế giới thời cận đại.'),
]

MEMBERS = [('tranthib', 'Trần Thị B'), ('lequangc', 'Lê Quang C'), ('phamthid', 'Phạm Thị D'),
           ('hoangvane', 'Hoàng Văn E'), ('vuthif', 'Vũ Thị F'), ('dangvang', 'Đặng Văn G'),
           ('buithih', 'Bùi Thị H'), ('dovani', 'Đỗ Văn I'), ('ngothik', 'Ngô Thị K'), ('lyvanl', 'Lý Văn L')]

REVIEWS = [
    (5, 'Nội dung dễ hiểu, ví dụ thực tế, rất hữu ích cho việc học.'),
    (4, 'Sách hay, trình bày rõ ràng, một vài chương hơi ngắn.'),
    (5, 'Một cuốn sách đáng đọc, mình đã giới thiệu cho bạn bè.'),
    (3, 'Nội dung ổn nhưng hơi khó với người mới bắt đầu.'),
    (4, 'Bản số đọc trực tuyến tiện lợi, chất lượng tốt.'),
    (5, 'Rất thích, đọc một mạch hết luôn.'),
    (4, 'Kiến thức bổ ích, phù hợp làm tài liệu tham khảo cho môn học.'),
]


def _get_or_create(model, name, **extra):
    obj = model.query.filter_by(name=name).first()
    if obj is None:
        obj = model(name=name, **extra)
        db.session.add(obj)
    return obj


def seed_demo_data(seed=2026):
    from .cli import _make_pdf
    rnd = random.Random(seed)
    today, now = date.today(), datetime.now()
    admin = User.query.filter_by(role='admin').first()
    folder = Path(current_app.config['DOCUMENT_FOLDER'])
    folder.mkdir(parents=True, exist_ok=True)
    added = {'categories': 0, 'books': 0, 'files': 0, 'members': 0}

    for name, desc in NEW_CATEGORIES:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name, description=desc))
            added['categories'] += 1
    db.session.flush()

    for i, (title, author, pub, cat, year, kw, qty, digital, desc) in enumerate(BOOKS):
        if Book.query.filter_by(title=title).first():
            continue
        book = Book(title=title, author=_get_or_create(Author, author), publisher=_get_or_create(Publisher, pub),
                    category=_get_or_create(Category, cat), publish_year=year, keywords=kw, description=desc,
                    quantity=qty, available=qty, image=IMG.format(COVERS[i % len(COVERS)]),
                    view_count=rnd.randint(10, 220), access_level=rnd.choice(['public', 'member', 'member']),
                    allow_download=rnd.random() > .3, created_at=now - timedelta(days=rnd.randint(1, 300)))
        db.session.add(book)
        db.session.flush()
        added['books'] += 1
        if digital:
            stored = f'demo_{book.id}.pdf'
            ascii_title = title.encode('ascii', 'ignore').decode().strip() or f'Tai lieu {book.id}'
            size = _make_pdf(folder / stored, ascii_title, [f'Tai lieu so: {ascii_title}', 'Ban demo phuc vu doc truc tuyen.'])
            db.session.add(DocumentFile(book=book, original_name=f'{title}.pdf', stored_name=stored,
                                        mime_type='application/pdf', file_size=size,
                                        uploaded_by=admin.id if admin else None))
            added['files'] += 1

    new_members = []
    for username, name in MEMBERS:
        if User.query.filter_by(username=username).first():
            continue
        u = User(username=username, full_name=name, email=f'{username}@gmail.com',
                 phone=f'09{rnd.randint(10000000, 99999999)}', created_at=now - timedelta(days=rnd.randint(30, 360)))
        u.set_password('password123')
        db.session.add(u)
        new_members.append(u)
    db.session.flush()
    added['members'] = len(new_members)

    # Hoạt động (mượn trả, đánh giá, truy cập...) chỉ tạo cho sinh viên mới thêm để chạy lại không bị nhân đôi
    if new_members:
        _activity(rnd, new_members, today, now)
    _sync_available()
    db.session.commit()
    return added


def _activity(rnd, members, today, now):
    books = Book.query.filter(Book.quantity > 0).all()
    digital = Book.query.filter(Book.files.any()).all()
    fine_per_day = 5000

    # Lịch sử mượn trả 12 tháng
    for _ in range(90):
        u, b = rnd.choice(members), rnd.choice(books)
        start = today - timedelta(days=rnd.randint(20, 360))
        due = start + timedelta(days=14)
        late = rnd.random() < .2
        ret = due + timedelta(days=rnd.randint(1, 10)) if late else start + timedelta(days=rnd.randint(3, 14))
        fine = max(0, (ret - due).days) * fine_per_day
        br = Borrowing(user=u, book=b, borrow_date=start, due_date=due, return_date=ret, status='returned',
                       fine_amount=fine, fine_paid=(rnd.random() > .25) if fine else False,
                       created_at=datetime.combine(start, datetime.min.time()))
        db.session.add(br)
        if rnd.random() < .2:
            db.session.add(BorrowRenewal(borrowing=br, old_due_date=due - timedelta(days=7), new_due_date=due))
    for _ in range(6):
        u, b = rnd.choice(members), rnd.choice(books)
        start = today - timedelta(days=rnd.randint(5, 120))
        db.session.add(Borrowing(user=u, book=b, borrow_date=start, due_date=start + timedelta(days=14),
                                 status='cancelled', notes='Người dùng tự hủy'))

    # Phiếu đang hoạt động: đang mượn (một số quá hạn) và chờ lấy, mỗi người không mượn trùng sách
    taken = set()

    def active(u, b, status, days_ago):
        """Phiếu đang hoạt động; hạn trả = ngày mượn + 14 ngày (mượn từ 15 ngày trước trở lên là quá hạn)."""
        if (u.id, b.id) in taken:
            return
        taken.add((u.id, b.id))
        start = today - timedelta(days=days_ago)
        db.session.add(Borrowing(user=u, book=b, borrow_date=start, due_date=start + timedelta(days=14),
                                 status=status, created_at=now - timedelta(days=days_ago)))

    for u in members[:8]:
        for b in rnd.sample(books, 2):
            active(u, b, 'borrowing', rnd.randint(15, 22) if rnd.random() < .25 else rnd.randint(2, 12))
    for u in members[2:5]:
        active(u, rnd.choice(books), 'pending', rnd.randint(0, 2))

    # Sách hết bản giấy và hàng chờ đặt trước
    hot = Book.query.filter_by(title='Mắt biếc').first() or books[0]
    for u in members[:hot.quantity]:
        active(u, hot, 'borrowing', 5)
    for u in members[6:9]:
        db.session.add(Reservation(user=u, book=hot, status='waiting',
                                   created_at=now - timedelta(days=rnd.randint(0, 4))))
    db.session.flush()

    # Đánh giá (mỗi người một lần cho mỗi sách)
    pairs = set()
    for _ in range(40):
        u, b = rnd.choice(members), rnd.choice(books)
        if (u.id, b.id) in pairs or Review.query.filter_by(user_id=u.id, book_id=b.id).first():
            continue
        pairs.add((u.id, b.id))
        rating, comment = rnd.choice(REVIEWS)
        db.session.add(Review(user=u, book=b, rating=rating, comment=comment,
                              created_at=now - timedelta(days=rnd.randint(1, 200))))

    # Lượt xem, đọc, tải 60 ngày gần nhất
    for d in range(60):
        for _ in range(rnd.randint(5, 18)):
            b = rnd.choice(digital) if digital else rnd.choice(books)
            action = rnd.choices(['view', 'read', 'download'], [5, 3, 1])[0] if b.files else 'view'
            db.session.add(AccessLog(user=rnd.choice(members + [None, None]), book=b,
                                     file=b.files[0] if action != 'view' else None, action=action,
                                     ip_address=f'10.0.{rnd.randint(0, 20)}.{rnd.randint(2, 250)}',
                                     created_at=now - timedelta(days=d, minutes=rnd.randint(0, 720))))

    # Tủ sách yêu thích và thông báo
    for u in members:
        for b in rnd.sample(books, 3):
            if not Favorite.query.filter_by(user_id=u.id, book_id=b.id).first():
                db.session.add(Favorite(user_id=u.id, book_id=b.id))
        db.session.add(Notification(user_id=u.id, message=f'Chào mừng {u.full_name} đến với thư viện số! '
                                                     'Bạn có thể tra cứu, đặt mượn và đọc tài liệu trực tuyến.',
                                    link='/books', created_at=now - timedelta(days=rnd.randint(1, 30))))
    members[-1].status = 'inactive'


def _sync_available():
    """Số bản còn lại = tổng số bản - số phiếu đang mượn/chờ lấy (tăng tổng số nếu cần để luôn hợp lệ)."""
    db.session.flush()
    counts = dict(db.session.execute(
        select(Borrowing.book_id, func.count(Borrowing.id))
        .where(Borrowing.status.in_(('pending', 'borrowing'))).group_by(Borrowing.book_id)).all())
    for book in Book.query.all():
        out = counts.get(book.id, 0)
        book.quantity = max(book.quantity, out)
        book.available = book.quantity - out
