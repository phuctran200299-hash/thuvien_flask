"""Trợ lý trả lời tự động không dùng AI (miễn phí, không cần mạng).

Dùng khi chưa cấu hình ANTHROPIC_API_KEY hoặc khi Claude API gặp sự cố. Mọi câu trả lời lấy từ CSDL thật:
- Nhận diện tên sách, tác giả, danh mục được nhắc trong câu (gõ không dấu, sai chính tả nhẹ vẫn nhận ra)
  và trả lời đúng khía cạnh được hỏi: còn sách không, tác giả, đọc online, nội dung, đánh giá.
- Hiểu bộ lọc trong câu: còn bản giấy, có bản số, khoảng năm xuất bản.
- Gợi ý sách hay/mới dựa trên lượt xem, lượt mượn, điểm đánh giá; thống kê kho tài liệu.
- Nhớ ngữ cảnh trong phiên chat: "còn cuốn nào khác không?", "cuốn đầu tiên còn không?".
- Trả lời quy định (giờ mở cửa, mượn, gia hạn, phạt, đặt trước...) theo trang Cài đặt và tài khoản cá nhân.
"""
import difflib
import re
import unicodedata

from flask import has_request_context, session
from sqlalchemy import func, select

from .extensions import db
from .models import Book, Borrowing, DocumentFile, Review


# ================================================
# CHUẨN HÓA VĂN BẢN
# ================================================
def norm(text):
    """Chữ thường, bỏ dấu tiếng Việt, chỉ giữ chữ và số (người dùng có thể gõ không dấu)."""
    text = unicodedata.normalize('NFD', (text or '').lower().replace('đ', 'd'))
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9+#]+', ' ', text).strip()


def has(q, *phrases):
    """q (đã chuẩn hóa) có chứa một trong các cụm từ (so khớp nguyên từ)."""
    padded = f' {q} '
    return any(f' {norm(p)} ' in padded for p in phrases)


def money(n):
    return f'{n:,}đ'.replace(',', '.')


STOPWORDS = set(norm(
    'cho tôi mình em anh chị bạn hỏi xin vui lòng giúp tìm kiếm tra cứu gợi ý giới thiệu đề xuất có không ko k khong '
    'nào gì cuốn quyển sách tài liệu về của thư viện muốn đọc cần là được hay hãy với các những một và hoặc thì nhé ạ '
    'à ơi đi nha liên quan tới đến loại chủ đề lĩnh vực ngành môn còn hết nữa thêm khác nào đâu ở trong bao nhiêu '
    'quyển cái này đó kia ai viết tác giả nội dung đọc online trực tuyến tải bản số mượn hiện tại bây giờ nên xem '
    'danh mục thể loại hay nhất mới nhất phổ biến top tốt năm sau trước từ xuất bản nxb nhà').split())

# Từ đồng nghĩa -> tên danh mục trong CSDL (chỉ dùng nếu danh mục tồn tại)
CATEGORY_SYNONYMS = {
    'Công nghệ thông tin': ['cntt', 'it', 'cong nghe thong tin', 'tin hoc', 'may tinh', 'phan mem'],
    'Kinh tế - Quản lý': ['kinh te', 'quan ly', 'quan tri', 'kinh doanh', 'tai chinh', 'marketing'],
    'Văn học': ['van hoc', 'tieu thuyet', 'truyen', 'tho', 'van chuong'],
    'Kỹ năng sống': ['ky nang', 'ky nang song', 'phat trien ban than', 'self help'],
    'Khoa học - Công nghệ': ['khoa hoc', 'vat ly', 'vu tru', 'thien van'],
    'Tâm lý - Tư duy': ['tam ly', 'tu duy'],
    'Ngoại ngữ': ['ngoai ngu', 'tieng anh', 'english', 'toeic', 'ielts'],
    'Lịch sử': ['lich su', 'su hoc'],
    'Thiếu nhi': ['thieu nhi', 'tre em', 'truyen tranh', 'cho be'],
}


# ================================================
# DANH MỤC TÀI LIỆU (đọc từ CSDL mỗi câu hỏi)
# ================================================
def load_catalog():
    files = dict(db.session.execute(select(DocumentFile.book_id, func.count(DocumentFile.id))
                                    .group_by(DocumentFile.book_id)).all())
    borrows = dict(db.session.execute(select(Borrowing.book_id, func.count(Borrowing.id))
                                      .where(Borrowing.status != 'cancelled').group_by(Borrowing.book_id)).all())
    ratings = {bid: (avg, n) for bid, avg, n in db.session.execute(
        select(Review.book_id, func.avg(Review.rating * 1.0), func.count(Review.id)).group_by(Review.book_id)).all()}
    catalog = []
    for b in Book.query.all():
        avg, n = ratings.get(b.id, (None, 0))
        item = {
            'id': b.id, 'title': b.title, 'author': b.author_name or '', 'publisher': b.publisher_name or '',
            'category': b.category.name if b.category else '', 'year': b.publish_year, 'available': b.available,
            'quantity': b.quantity, 'digital': files.get(b.id, 0) > 0, 'public': b.access_level == 'public',
            'download': b.allow_download, 'views': b.view_count, 'borrows': borrows.get(b.id, 0),
            'rating': round(avg, 1) if avg else None, 'reviews': n, 'description': b.description or '',
            'keywords': b.keywords or '', 'created': b.created_at,
        }
        item['n_title'], item['n_author'], item['n_cat'] = norm(item['title']), norm(item['author']), norm(item['category'])
        item['n_main'] = norm(item['title'].split(':')[0])  # "Sapiens: Lược sử loài người" -> "sapiens"
        item['n_kw'], item['n_desc'] = norm(item['keywords']), norm(item['description'])
        item['popularity'] = item['views'] + item['borrows'] * 5 + (item['rating'] or 3) * item['reviews'] * 3
        catalog.append(item)
    return catalog


def vocabulary(catalog):
    words = set()
    for b in catalog:
        words.update(w for w in f"{b['n_title']} {b['n_author']} {b['n_cat']} {b['n_kw']}".split() if len(w) >= 3)
    return words


def correct(tokens, vocab):
    """Sửa lỗi chính tả nhẹ theo từ vựng của kho tài liệu (vd. 'trnh' -> 'trinh')."""
    out = []
    for t in tokens:
        if t in vocab or t in STOPWORDS or len(t) < 3 or t.isdigit():
            out.append(t)
        else:
            close = difflib.get_close_matches(t, vocab, n=1, cutoff=0.75)
            out.append(close[0] if close else t)
    return out


# ================================================
# NHẬN DIỆN THỰC THỂ TRONG CÂU HỎI
# ================================================
def find_title(q, catalog):
    """Tên sách được nhắc trong câu (khớp nguyên cụm, hoặc gần đúng khi gõ sai chính tả)."""
    best, best_score = None, 0
    for b in catalog:
        title, main = b['n_title'], b['n_main']
        words = main.split()
        if not words:
            continue
        if f' {title} ' in f' {q} ':
            score = 10 + len(words)
        elif f' {main} ' in f' {q} ' and (len(words) >= 2 or len(main) >= 6):
            score = 8 + len(words)
        elif len(words) >= 2:
            # Gần đúng: so cụm từ cùng độ dài trong câu với tên sách
            qw = q.split()
            score = 0
            for i in range(len(qw) - len(words) + 1):
                ratio = difflib.SequenceMatcher(None, ' '.join(qw[i:i + len(words)]), main).ratio()
                if ratio >= 0.85:
                    score = max(score, 5 + ratio * len(words))
        else:
            continue
        if score > best_score:
            best, best_score = b, score
    return best


def find_author(q, catalog):
    best, best_len = None, 0
    for b in catalog:
        a = b['n_author']
        if not a:
            continue
        last = a.split()[-1]
        if f' {a} ' in f' {q} ' or (len(last) >= 5 and len(a.split()) >= 2 and f' {last} ' in f' {q} '
                                     and not norm(last) in ('nguyen', 'tran', 'pham')):
            if len(a) > best_len:
                best, best_len = b['author'], len(a)
    return best


def find_category(q, catalog):
    """Trả về (tên danh mục, cụm từ đã khớp trong câu) hoặc (None, '')."""
    names = {b['category'] for b in catalog if b['category']}
    for name in sorted(names, key=len, reverse=True):
        if has(q, name):
            return name, norm(name)
    for name, syns in CATEGORY_SYNONYMS.items():
        if name in names:
            for s in sorted(syns, key=len, reverse=True):
                if has(q, s):
                    return name, s
    return None, ''


def find_filters(q):
    f = {}
    if has(q, 'con sach', 'con ban', 'con khong', 'muon duoc', 'con muon', 'san sang', 'chua het'):
        f['available'] = True
    if has(q, 'ban so', 'doc online', 'doc truc tuyen', 'ebook', 'pdf', 'doc tren web', 'tai ve'):
        f['digital'] = True
    m = re.search(r'(sau|tu) (nam )?((19|20)\d\d)', q)
    if m:
        f['year_from'] = int(m.group(3)) + (1 if m.group(1) == 'sau' else 0)
    m = re.search(r'truoc (nam )?((19|20)\d\d)', q)
    if m:
        f['year_to'] = int(m.group(2)) - 1
    m = re.search(r'nam ((19|20)\d\d)', q)
    if m and 'year_from' not in f and 'year_to' not in f:
        f['year_from'] = f['year_to'] = int(m.group(1))
    return f


def apply_filters(books, f):
    if f.get('available'):
        books = [b for b in books if b['available'] > 0]
    if f.get('digital'):
        books = [b for b in books if b['digital']]
    if f.get('year_from'):
        books = [b for b in books if b['year'] and b['year'] >= f['year_from']]
    if f.get('year_to'):
        books = [b for b in books if b['year'] and b['year'] <= f['year_to']]
    return books


def search(tokens, catalog):
    """Tìm theo từ khóa, xếp hạng: khớp tên sách > tác giả/danh mục/từ khóa > mô tả."""
    tokens = [t for t in tokens if t not in STOPWORDS and (len(t) >= 2 or t.isdigit())]
    if not tokens:
        return []
    phrase = ' '.join(tokens)
    scored = []
    for b in catalog:
        fields = [(b['n_title'], 4), (b['n_author'], 3), (b['n_cat'], 2), (b['n_kw'], 3), (b['n_desc'], 1)]
        score, hits = 0, 0
        for t in tokens:
            best = max((w for text, w in fields if f' {t} ' in f' {text} '), default=0)
            score += best
            hits += best > 0
        if len(tokens) > 1 and any(f' {phrase} ' in f' {text} ' for text, _ in fields[:4]):
            score += 5
        need = 1 if len(tokens) == 1 else max(2, (len(tokens) + 1) // 2)
        if hits >= need:
            scored.append((score, b['popularity'], b))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [b for _, _, b in scored]


# ================================================
# ĐỊNH DẠNG CÂU TRẢ LỜI
# ================================================
def status(b):
    if not b['quantity']:
        return 'không có bản giấy'
    return f"còn {b['available']}/{b['quantity']} bản giấy" if b['available'] else 'đã hết bản giấy'


def book_line(b):
    extra = []
    if b['digital']:
        extra.append('có bản số')
    if b['rating']:
        extra.append(f"★{b['rating']}")
    author = f" - {b['author']}" if b['author'] else ''
    return f"- \"{b['title']}\"{author} ({status(b)}{', ' + ', '.join(extra) if extra else ''}) /books/{b['id']}"


def book_list(intro, books, offset=0, size=5):
    page = books[offset:offset + size]
    lines = [intro] + [book_line(b) for b in page]
    if len(books) > offset + size:
        lines.append(f'Còn {len(books) - offset - size} tài liệu khác, bạn hỏi "còn cuốn nào khác không?" để xem tiếp.')
    remember([b['id'] for b in books], offset + len(page))
    return '\n'.join(lines)


def remember(ids, shown):
    """Lưu danh sách vừa trả lời vào phiên để hiểu câu hỏi tiếp theo ("còn cuốn nào khác", "cuốn đầu tiên")."""
    if has_request_context():
        session['chat_ctx'] = {'ids': ids[:50], 'shown': shown}


def context():
    return session.get('chat_ctx') if has_request_context() else None


def book_detail(b, q):
    link = f"/books/{b['id']}"
    remember([b['id']], 1)
    if has(q, 'ai viet', 'tac gia', 'cua ai'):
        return f"\"{b['title']}\" do {b['author'] or 'chưa rõ tác giả'} viết" + \
               (f", {b['publisher']} xuất bản năm {b['year']}" if b['year'] else '') + f'. Chi tiết: {link}'
    if has(q, 'doc online', 'doc truc tuyen', 'ban so', 'ebook', 'pdf', 'tai ve', 'doc duoc', 'tai duoc'):
        if not b['digital']:
            return f"\"{b['title']}\" hiện chưa có bản số, bạn có thể mượn bản giấy ({status(b)}). {link}"
        who = 'ai cũng đọc được' if b['public'] else 'cần đăng nhập để đọc'
        dl = 'cho phép tải về' if b['download'] else 'chỉ đọc trực tuyến, không cho tải về'
        return f"\"{b['title']}\" có bản số: {who}, {dl}. Bấm \"Đọc trực tuyến\" tại {link}"
    if has(q, 'noi dung', 've gi', 'gioi thieu', 'tom tat', 'noi ve'):
        desc = b['description'] or 'Thư viện chưa có mô tả cho tài liệu này.'
        return f"\"{b['title']}\" ({b['author'] or 'chưa rõ tác giả'}): {desc} {link}"
    if has(q, 'danh gia', 'review', 'co hay', 'hay khong', 'diem'):
        if not b['reviews']:
            return f"\"{b['title']}\" chưa có đánh giá nào. Bạn có thể đánh giá sau khi mượn hoặc đọc. {link}"
        return f"\"{b['title']}\" được đánh giá ★{b['rating']}/5 ({b['reviews']} lượt), {b['borrows']} lượt mượn. {link}"
    if has(q, 'con', 'het', 'muon duoc', 'muon', 'dat muon', 'con khong'):
        if not b['quantity']:
            return f"Thư viện không có bản giấy của \"{b['title']}\"" + \
                   (', nhưng có bản số đọc trực tuyến.' if b['digital'] else '.') + f' {link}'
        if b['available']:
            return (f"\"{b['title']}\" còn {b['available']}/{b['quantity']} bản giấy, bạn đăng nhập rồi bấm "
                    f"\"Đặt mượn sách\" tại {link} và đến thư viện nhận sách.")
        return (f"\"{b['title']}\" đã hết bản giấy. Bạn bấm \"Đăng ký chờ sách\" tại {link}, khi có người trả "
                'thư viện sẽ giữ sách và báo cho bạn.')
    parts = [f"\"{b['title']}\"", f"- Tác giả: {b['author'] or 'chưa rõ'}"]
    if b['category']:
        parts.append(f"- Danh mục: {b['category']}" + (f", năm xuất bản {b['year']}" if b['year'] else ''))
    parts.append(f"- Bản giấy: {status(b)}" + ('; có bản số đọc trực tuyến' if b['digital'] else ''))
    if b['rating']:
        parts.append(f"- Đánh giá: ★{b['rating']}/5 ({b['reviews']} lượt)")
    parts.append(f'Xem chi tiết, đặt mượn hoặc đọc tại {link}')
    return '\n'.join(parts)


# ================================================
# CÁC NHÓM CÂU HỎI CỐ ĐỊNH (quy định, liên hệ, tài khoản)
# ================================================
def rules():
    from .services import get_setting_int
    return {k: get_setting_int(k, d) for k, d in (
        ('max_borrow_days', 14), ('max_books_per_user', 5), ('max_renewals', 2), ('renew_days', 7),
        ('pending_expire_days', 3), ('fine_per_day', 5000))}


def my_account(user):
    from .chatbot import _my_account
    if user is None or not user.is_authenticated:
        return 'Bạn cần đăng nhập để xem sách đang mượn, hạn trả và tiền phạt của mình. Đăng nhập tại /login nhé.'
    acc = _my_account(user)
    lines = []
    if acc['phieu_dang_hoat_dong']:
        lines.append(f"{acc['ho_ten']} đang có {len(acc['phieu_dang_hoat_dong'])} phiếu:")
        for b in acc['phieu_dang_hoat_dong']:
            fine = f", phạt tạm tính {money(b['tien_phat_tam_tinh'])}" if b['tien_phat_tam_tinh'] else ''
            lines.append(f"- \"{b['sach']}\": {b['trang_thai']}, hạn trả {b['han_tra']}{fine}")
    else:
        lines.append('Hiện bạn không có phiếu mượn nào đang hoạt động.')
    if acc['tien_phat_chua_dong']:
        lines.append(f"Tiền phạt chưa đóng: {money(acc['tien_phat_chua_dong'])} (thanh toán tại quầy thư viện).")
    if acc['dang_cho_dat_truoc']:
        lines.append('Đang chờ đặt trước: ' + ', '.join(f'"{t}"' for t in acc['dang_cho_dat_truoc']) + '.')
    lines.append('Xem chi tiết và gia hạn tại /my-books.')
    return '\n'.join(lines)


def fixed_answer(q, user):
    from .services import get_setting
    r = rules()
    if has(q, 'toi dang muon', 'cua toi', 'cua minh', 'toi muon', 'minh muon', 'em muon', 'em dang muon',
           'toi no', 'minh no', 'han tra cua toi', 'tai khoan cua toi', 'phieu cua toi', 'sach cua toi'):
        return my_account(user)
    if has(q, 'gio mo cua', 'mo cua', 'dong cua', 'may gio', 'gio lam viec', 'thoi gian mo', 'lam viec luc'):
        return f"Giờ mở cửa của thư viện: {get_setting('opening_hours')}."
    if has(q, 'dia chi', 'o dau', 'lien he', 'so dien thoai', 'sdt', 'hotline', 'email', 'zalo'):
        return (f"Thông tin liên hệ thư viện:\n- Địa chỉ: {get_setting('contact_address')}\n"
                f"- Điện thoại: {get_setting('contact_phone')}\n- Email: {get_setting('contact_email')}\n"
                f"- Giờ mở cửa: {get_setting('opening_hours')}")
    if has(q, 'gia han'):
        return (f"Bạn được gia hạn tối đa {r['max_renewals']} lần cho mỗi phiếu, mỗi lần thêm {r['renew_days']} ngày. "
                'Không gia hạn được khi sách đã quá hạn. Bấm "Gia hạn" tại trang Sách của tôi: /my-books')
    if has(q, 'phat', 'tra tre', 'tra muon', 'qua han', 'nop phat'):
        return (f"Trả sách trễ bị phạt {money(r['fine_per_day'])} cho mỗi ngày trễ. Tiền phạt thanh toán tại quầy "
                'thư viện; khi còn nợ phạt bạn chưa thể đặt mượn thêm.')
    if has(q, 'dat truoc', 'het sach', 'dang ky cho', 'hang cho', 'sach het'):
        return (f"Khi sách đã hết, bạn mở trang chi tiết sách và bấm \"Đăng ký chờ sách\". Khi có người trả, hệ thống "
                f"tự giữ sách cho người đầu hàng chờ trong {r['pending_expire_days']} ngày và gửi thông báo cho bạn.")
    if has(q, 'tra sach', 'tra o dau', 'nop sach'):
        return f"Bạn trả sách trực tiếp tại quầy thư viện ({get_setting('contact_address')}) trong giờ mở cửa."
    if has(q, 'mang gi', 'can mang', 'giay to', 'the sinh vien', 'cccd'):
        return 'Khi đến nhận sách, bạn mang theo thẻ sinh viên hoặc CCCD để thủ thư xác nhận.'
    if has(q, 'dang ky tai khoan', 'tao tai khoan', 'dang ky', 'dang nhap', 'quen mat khau', 'mat khau'):
        return ('Đăng ký tài khoản tại /register, đăng nhập tại /login. Đổi mật khẩu tại trang Thông tin cá nhân '
                '(/profile). Nếu quên mật khẩu, bạn liên hệ thư viện để quản trị viên đặt lại.')
    if has(q, 'quy dinh', 'muon bao lau', 'duoc bao lau', 'bao lau', 'bao nhieu cuon', 'muon toi da', 'cach muon',
           'muon the nao', 'muon nhu the nao', 'dat muon the nao', 'lam sao de muon', 'muon sach'):
        return (f"Quy định mượn sách:\n- Mượn tối đa {r['max_books_per_user']} cuốn cùng lúc, mỗi cuốn "
                f"{r['max_borrow_days']} ngày.\n- Gia hạn tối đa {r['max_renewals']} lần, mỗi lần {r['renew_days']} ngày.\n"
                f"- Đặt mượn trên website rồi đến thư viện nhận sách trong {r['pending_expire_days']} ngày, mang thẻ sinh "
                f"viên hoặc CCCD.\n- Trả trễ phạt {money(r['fine_per_day'])}/ngày.")
    return None


DIGITAL_HELP = ('Tài liệu có nhãn "Bản số" đọc được trực tuyến: mở trang chi tiết và bấm "Đọc trực tuyến". Tài liệu '
                '"công khai" ai cũng đọc được, tài liệu "thành viên" cần đăng nhập; nút "Tải về" chỉ hiện với tài liệu '
                'cho phép tải. Xem các tài liệu số tại /books?digital=1')


# ================================================
# TRẢ LỜI
# ================================================
def answer(question, user=None):
    q = norm(question)
    if not q:
        return 'Bạn muốn hỏi gì về thư viện?'
    words = q.split()

    if has(q, 'cam on', 'thank', 'thanks', 'cảm ơn'):
        return 'Rất vui được giúp bạn! Cần tìm thêm tài liệu nào cứ hỏi mình nhé.'
    if len(words) <= 4 and has(q, 'xin chao', 'chao', 'hello', 'hi', 'alo', 'chao ban', 'hey'):
        return ('Xin chào! Mình là trợ lý của thư viện. Bạn có thể hỏi về sách (ví dụ "sách về Python", "Nhà giả kim '
                'còn không?"), gợi ý sách hay, giờ mở cửa, quy định mượn trả, tiền phạt hoặc sách bạn đang mượn.')

    catalog = load_catalog()
    by_id = {b['id']: b for b in catalog}
    ctx = context()

    # Câu hỏi tiếp theo dựa trên danh sách vừa trả lời
    if ctx and ctx.get('ids'):
        if has(q, 'con cuon nao', 'cuon nao khac', 'con nua', 'them nua', 'xem them', 'con khong nua', 'cuon khac',
               'sach khac', 'tiep', 'con gi nua') and not find_title(q, catalog):
            books = [by_id[i] for i in ctx['ids'] if i in by_id]
            if ctx['shown'] >= len(books):
                return 'Mình đã liệt kê hết các tài liệu phù hợp rồi. Bạn thử hỏi chủ đề khác nhé.'
            return book_list('Các tài liệu tiếp theo:', books, ctx['shown'])
        m = re.search(r'cuon (dau tien|thu nhat|thu hai|thu ba|thu tu|thu nam|so \d|\d|do|nay|tren|cuoi)', q)
        if m:
            order = {'dau tien': 0, 'thu nhat': 0, 'thu hai': 1, 'thu ba': 2, 'thu tu': 3, 'thu nam': 4, 'do': 0,
                     'nay': 0, 'tren': 0}
            key = m.group(1)
            idx = int(re.sub(r'\D', '', key)) - 1 if re.search(r'\d', key) else order.get(key, 0)
            if key == 'cuoi':
                idx = min(ctx['shown'], len(ctx['ids'])) - 1
            if 0 <= idx < len(ctx['ids']) and ctx['ids'][idx] in by_id:
                return book_detail(by_id[ctx['ids'][idx]], q)

    fixed = fixed_answer(q, user)
    title_book = find_title(q, catalog)
    if title_book and not (fixed and has(q, 'gio mo cua', 'dia chi', 'lien he')):
        return book_detail(title_book, q)
    if fixed:
        return fixed

    # Thống kê kho tài liệu
    if has(q, 'bao nhieu', 'tong so', 'so luong') and has(q, 'sach', 'tai lieu', 'dau sach', 'danh muc', 'the loai', 'ban so'):
        cats = sorted({b['category'] for b in catalog if b['category']})
        return (f"Thư viện hiện có {len(catalog)} đầu tài liệu ({sum(b['quantity'] for b in catalog)} bản giấy, "
                f"{sum(b['digital'] for b in catalog)} tài liệu có bản số) thuộc {len(cats)} danh mục: {', '.join(cats)}.")
    if has(q, 'danh muc nao', 'the loai nao', 'nhung loai', 'loai sach nao', 'chu de nao', 'co nhung danh muc',
           'co nhung the loai', 'danh muc gi', 'the loai gi'):
        counts = {}
        for b in catalog:
            if b['category']:
                counts[b['category']] = counts.get(b['category'], 0) + 1
        return 'Thư viện có các danh mục:\n' + '\n'.join(f'- {c} ({n} tài liệu)' for c, n in sorted(counts.items())) + \
               '\nBạn hỏi "sách <danh mục>" để xem gợi ý, ví dụ "sách văn học".'

    filters = find_filters(q)
    author = find_author(q, catalog)
    category, cat_phrase = find_category(q, catalog)

    if author:
        books = apply_filters(sorted((b for b in catalog if b['author'] == author), key=lambda b: -b['popularity']), filters)
        if not books:
            return f'Thư viện chưa có tài liệu nào của {author} phù hợp yêu cầu.'
        return book_list(f'Tài liệu của {author} trong thư viện:', books)

    wants_new = has(q, 'moi nhat', 'sach moi', 'moi ve', 'vua them', 'moi cap nhat')
    wants_top = has(q, 'hay nhat', 'sach hay', 'noi bat', 'pho bien', 'nen doc', 'doc nhieu', 'muon nhieu',
                    'yeu thich', 'top', 'hot', 'nhieu nguoi', 'hay', 'dang doc')
    tokens = correct(words, vocabulary(catalog))
    # Từ thuộc tên danh mục, bộ lọc (còn sách, bản số, năm) không phải chủ đề cần tìm
    noise = set(cat_phrase.split()) | set(norm('hay moi nhat top hot ban so doc online truc tuyen ebook pdf con '
                                               'muon duoc san sang xuat sau truoc tu nam co').split())
    topic = [t for t in tokens if t not in STOPWORDS and t not in noise and not t.isdigit()]
    order = (lambda b: -b['created'].timestamp()) if wants_new else (lambda b: -b['popularity'])
    cond = []
    if filters.get('available'):
        cond.append('còn bản giấy')
    if filters.get('digital'):
        cond.append('có bản số')
    if filters.get('year_from') and filters.get('year_to') and filters['year_from'] == filters['year_to']:
        cond.append(f"xuất bản năm {filters['year_from']}")
    else:
        if filters.get('year_from'):
            cond.append(f"xuất bản từ năm {filters['year_from']}")
        if filters.get('year_to'):
            cond.append(f"xuất bản đến năm {filters['year_to']}")
    cond_text = f" ({', '.join(cond)})" if cond else ''

    if category and not topic:
        books = apply_filters(sorted((b for b in catalog if b['category'] == category), key=order), filters)
        if not books:
            return f'Danh mục {category} chưa có tài liệu nào phù hợp yêu cầu{cond_text}.'
        return book_list(f"{'Tài liệu mới' if wants_new else 'Gợi ý tài liệu'} thuộc danh mục {category}{cond_text}:", books)

    if not topic and (wants_new or wants_top or filters):
        books = apply_filters(sorted(catalog, key=order), filters)
        if not books:
            return f'Thư viện chưa có tài liệu nào{cond_text}.'
        if wants_new:
            return book_list(f'Tài liệu mới bổ sung gần đây{cond_text}:', books)
        if wants_top:
            return book_list(f'Tài liệu được đọc, mượn và đánh giá cao nhất{cond_text}:', books)
        return book_list(f'Các tài liệu{cond_text}:', books)

    if not topic and has(q, 'doc online', 'doc truc tuyen', 'tai lieu so', 'ban so', 'ebook', 'tai ve', 'download'):
        return DIGITAL_HELP

    results = search(topic, catalog)
    if category:
        results = [b for b in results if b['category'] == category] or results
    results = apply_filters(results, filters)
    phrase = ' '.join(w for w in question.split()
                      if norm(w) and norm(w) not in STOPWORDS and norm(w) not in noise).strip(' ?.!,') or question
    if category and cat_phrase:
        phrase = f'{phrase} - {category}' if norm(phrase) != cat_phrase else category
    if results:
        return book_list(f'Thư viện có {len(results)} tài liệu liên quan tới "{phrase}"{cond_text}:', results)

    if filters and (search(topic, catalog) or category):
        return f'Có tài liệu về "{phrase}" nhưng không có cuốn nào thỏa điều kiện bạn yêu cầu (còn sách, bản số, năm...).'
    # Gợi ý tên sách gần giống khi gõ sai
    guess = difflib.get_close_matches(q, [b['n_title'] for b in catalog], n=3, cutoff=0.5)
    if guess:
        books = [b for b in catalog if b['n_title'] in guess]
        return book_list('Mình chưa tìm thấy chính xác, có phải bạn muốn tìm:', books)
    if topic:
        return (f'Mình chưa tìm thấy tài liệu nào phù hợp với "{phrase}". Bạn thử từ khóa khác (tên sách, tác giả, '
                'chủ đề) hoặc xem toàn bộ kho tài liệu tại /books nhé.')
    from .services import get_setting
    return ('Mình chưa hiểu câu hỏi. Bạn có thể hỏi: tên sách hoặc chủ đề cần tìm, "sách nào hay", "sách mới nhất", '
            '"Nhà giả kim còn không", giờ mở cửa, quy định mượn trả, gia hạn, tiền phạt, sách bạn đang mượn; '
            f"hoặc gọi hotline {get_setting('contact_phone')}.")
