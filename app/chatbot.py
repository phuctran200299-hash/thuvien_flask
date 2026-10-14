"""Trợ lý AI hỏi đáp về thư viện (Claude API).

Claude trả lời dựa trên dữ liệu thật của thư viện qua các công cụ (tool use):
- search_books: tra cứu tài liệu trong CSDL
- get_my_account: phiếu mượn, hạn trả, tiền phạt, hàng chờ của người đang đăng nhập

Lịch sử hội thoại do trình duyệt giữ và gửi lên dạng văn bản; trong một lượt hỏi, các phản hồi
có gọi công cụ được gửi lại nguyên vẹn (kể cả thinking block) cho tới khi Claude trả lời xong.
"""
import json
import logging

import anthropic
from flask import current_app
from sqlalchemy import or_, select

from .extensions import db
from .models import Author, Book, Borrowing, Category, Publisher, Reservation

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
MAX_HISTORY = 12          # số tin nhắn gần nhất gửi kèm
MAX_MESSAGE_CHARS = 1000

TOOLS = [
    {
        'name': 'search_books',
        'description': (
            'Tra cứu tài liệu trong kho của thư viện theo tên sách, tác giả, nhà xuất bản, ISBN, từ khóa, mô tả '
            'hoặc tên danh mục. Trả về tối đa 8 kết quả kèm số bản giấy còn sẵn, có bản số hay không và đường '
            'dẫn trang chi tiết. Dùng mỗi khi người dùng hỏi về một cuốn sách, chủ đề, tác giả hoặc cần gợi ý tài liệu.'
        ),
        'strict': True,
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Từ khóa tìm kiếm, ví dụ "python", "Paulo Coelho"'},
                'only_available': {'type': 'boolean', 'description': 'Chỉ lấy sách còn bản giấy để mượn'},
                'digital_only': {'type': 'boolean', 'description': 'Chỉ lấy tài liệu có bản số đọc trực tuyến'},
            },
            'required': ['query', 'only_available', 'digital_only'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_my_account',
        'description': (
            'Lấy thông tin tài khoản của người đang chat: sách đang mượn và hạn trả, phiếu chờ lấy, sách quá hạn, '
            'tiền phạt chưa đóng, các sách đang đăng ký chờ. Chỉ dùng khi người dùng hỏi về sách/phiếu/phạt của chính họ.'
        ),
        'strict': True,
        'input_schema': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
    },
]


class ChatError(Exception):
    """Lỗi hiển thị được cho người dùng."""


def _client():
    client = current_app.extensions.get('anthropic_client')
    if client is None:
        # Thông tin xác thực lấy từ biến môi trường ANTHROPIC_API_KEY (file .env)
        client = anthropic.Anthropic(timeout=60.0, max_retries=2)
        current_app.extensions['anthropic_client'] = client
    return client


def _system_prompt():
    from .services import get_setting, get_setting_int
    rules = {
        'Số ngày mượn': f"{get_setting_int('max_borrow_days', 14)} ngày",
        'Số sách mượn tối đa cùng lúc (tính cả phiếu chờ lấy)': get_setting_int('max_books_per_user', 5),
        'Gia hạn': f"tối đa {get_setting_int('max_renewals', 2)} lần, mỗi lần {get_setting_int('renew_days', 7)} ngày, "
                   'không gia hạn được khi đã quá hạn',
        'Giữ sách cho phiếu đặt mượn': f"{get_setting_int('pending_expire_days', 3)} ngày, quá hạn tự hủy",
        'Phạt trả trễ': f"{get_setting_int('fine_per_day', 5000):,}đ/ngày".replace(',', '.'),
    }
    info = {
        'Tên thư viện': get_setting('site_name'),
        'Địa chỉ': get_setting('contact_address'),
        'Điện thoại': get_setting('contact_phone'),
        'Email': get_setting('contact_email'),
        'Giờ mở cửa': get_setting('opening_hours'),
    }
    lines = '\n'.join(f'- {k}: {v}' for k, v in {**info, **rules}.items())
    return f"""Bạn là trợ lý ảo của website thư viện số Trường Đại học Công nghiệp Việt Trì. Bạn giúp sinh viên, giảng viên \
và khách tra cứu tài liệu, hiểu quy định mượn trả và cách dùng website. Luôn trả lời bằng tiếng Việt, thân thiện, ngắn gọn.

Thông tin và quy định của thư viện:
{lines}

Cách dùng website:
- Tra cứu ở trang "Tài liệu" (/books): lọc theo danh mục, tác giả, NXB, năm xuất bản, còn bản giấy, có bản số.
- Đặt mượn bản giấy: đăng nhập, mở trang chi tiết sách, bấm "Đặt mượn sách", rồi đến thư viện nhận sách trong thời gian giữ sách. \
Mang thẻ sinh viên hoặc CCCD. Trả sách tại quầy.
- Sách đã hết: bấm "Đăng ký chờ sách"; khi có sách trả về hệ thống tự giữ sách cho người đầu hàng chờ và gửi thông báo.
- Gia hạn, hủy phiếu chờ, xem lịch sử mượn, tài liệu đã đọc, tủ sách yêu thích: trang "Sách của tôi" (/my-books).
- Tài liệu số: tài liệu "công khai" ai cũng đọc được; tài liệu "thành viên" phải đăng nhập; có tài liệu chỉ cho đọc trực tuyến, không cho tải.
- Còn nợ phạt thì không đặt mượn thêm được cho đến khi thanh toán tại quầy.
- Thông báo (nhắc hạn trả, sách đặt trước đã có...) ở biểu tượng chuông trên thanh menu (/notifications).
- Quên mật khẩu: liên hệ thư viện để quản trị viên đặt lại.

Nguyên tắc:
- Khi hỏi về sách cụ thể hoặc cần gợi ý tài liệu, luôn dùng công cụ search_books; chỉ giới thiệu sách có trong kết quả, không bịa sách.
- Khi giới thiệu một cuốn sách, ghi kèm đường dẫn dạng /books/<id> lấy từ kết quả để người dùng bấm vào.
- Hỏi về sách đang mượn, hạn trả, tiền phạt của chính người dùng thì dùng get_my_account. Nếu công cụ báo chưa đăng nhập, \
hướng dẫn họ đăng nhập.
- Bạn không tự đặt mượn, gia hạn hay hủy phiếu thay người dùng; hãy hướng dẫn họ thao tác trên website.
- Câu hỏi không liên quan tới thư viện, học tập hay tài liệu thì từ chối nhẹ nhàng và gợi ý điều bạn có thể giúp.
- Viết văn bản thường, có thể dùng gạch đầu dòng "-"; không dùng bảng, không dùng tiêu đề Markdown."""


# ================================================
# CÔNG CỤ
# ================================================
def _search_books(query, only_available=False, digital_only=False):
    query = (query or '').strip()[:100]
    stmt = (select(Book).outerjoin(Author, Book.author_id == Author.id)
            .outerjoin(Publisher, Book.publisher_id == Publisher.id)
            .outerjoin(Category, Book.category_id == Category.id))
    if query:
        like = f'%{query}%'
        stmt = stmt.where(or_(Book.title.ilike(like), Author.name.ilike(like), Publisher.name.ilike(like),
                              Book.isbn.ilike(like), Book.keywords.ilike(like), Book.description.ilike(like),
                              Category.name.ilike(like)))
    if only_available:
        stmt = stmt.where(Book.available > 0)
    if digital_only:
        stmt = stmt.where(Book.files.any())
    books = db.session.scalars(stmt.order_by(Book.view_count.desc(), Book.id.desc()).limit(8)).all()
    return {
        'so_ket_qua': len(books),
        'ket_qua': [{
            'id': b.id, 'ten': b.title, 'tac_gia': b.author_name, 'nha_xuat_ban': b.publisher_name,
            'danh_muc': b.category.name if b.category else None, 'nam_xuat_ban': b.publish_year,
            'ban_giay_con_san': b.available, 'tong_ban_giay': b.quantity,
            'co_ban_so': bool(b.files), 'quyen_doc_ban_so': 'công khai' if b.access_level == 'public' else 'thành viên',
            'cho_tai_ve': b.allow_download, 'mo_ta': (b.description or '')[:200], 'duong_dan': f'/books/{b.id}',
        } for b in books],
    }


def _my_account(user):
    if user is None or not user.is_authenticated:
        return {'loi': 'Người dùng chưa đăng nhập.'}
    from .services import calculate_fine, unpaid_fine
    borrows = Borrowing.query.filter(Borrowing.user_id == user.id,
                                     Borrowing.status.in_(('pending', 'borrowing'))).all()
    reservations = Reservation.query.filter_by(user_id=user.id, status='waiting').all()
    return {
        'ho_ten': user.full_name,
        'phieu_dang_hoat_dong': [{
            'sach': b.book.title, 'trang_thai': b.status_label, 'han_tra': f'{b.due_date:%d/%m/%Y}',
            'so_lan_da_gia_han': b.renew_count,
            'tien_phat_tam_tinh': calculate_fine(b.due_date) if b.is_overdue else 0,
        } for b in borrows],
        'tien_phat_chua_dong': unpaid_fine(user.id),
        'dang_cho_dat_truoc': [r.book.title for r in reservations],
    }


def _run_tool(name, args, user):
    if name == 'search_books':
        return _search_books(args.get('query', ''), bool(args.get('only_available')), bool(args.get('digital_only')))
    if name == 'get_my_account':
        return _my_account(user)
    return {'loi': f'Không có công cụ {name}'}


# ================================================
# HỘI THOẠI
# ================================================
def clean_history(raw):
    """Chuẩn hóa lịch sử từ trình duyệt: chỉ văn bản, vai trò xen kẽ, bắt đầu và kết thúc bằng user."""
    if not isinstance(raw, list):
        raise ChatError('Dữ liệu không hợp lệ')
    messages = []
    for item in raw[-MAX_HISTORY:]:
        if not isinstance(item, dict) or item.get('role') not in ('user', 'assistant'):
            continue
        text = str(item.get('content') or '').strip()[:MAX_MESSAGE_CHARS * 2]
        if not text:
            continue
        if messages and messages[-1]['role'] == item['role']:
            messages[-1]['content'] += '\n' + text
        else:
            messages.append({'role': item['role'], 'content': text})
    while messages and messages[0]['role'] != 'user':
        messages.pop(0)
    if not messages or messages[-1]['role'] != 'user':
        raise ChatError('Vui lòng nhập câu hỏi')
    if len(messages[-1]['content']) > MAX_MESSAGE_CHARS:
        raise ChatError(f'Câu hỏi tối đa {MAX_MESSAGE_CHARS} ký tự')
    return messages


def ask(history, user=None):
    """Gửi hội thoại tới Claude, xử lý gọi công cụ, trả về câu trả lời dạng văn bản."""
    messages = clean_history(history)
    client = _client()
    system = _system_prompt()
    model = current_app.config['CHATBOT_MODEL']

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                tools=TOOLS,
                messages=messages,
                output_config={'effort': 'low'},  # hỏi đáp ngắn: ưu tiên nhanh, tiết kiệm
                # Nếu bị bộ lọc an toàn từ chối nhầm, API tự chạy lại trên model dự phòng
                betas=['server-side-fallback-2026-07-01'],
                fallbacks='default',
            )
        except anthropic.AuthenticationError:
            log.error('Chatbot: ANTHROPIC_API_KEY không hợp lệ hoặc chưa cấu hình')
            raise ChatError('Trợ lý AI chưa được cấu hình. Vui lòng liên hệ quản trị viên.')
        except anthropic.RateLimitError:
            raise ChatError('Trợ lý đang quá tải, vui lòng thử lại sau ít phút.')
        except anthropic.APIConnectionError:
            raise ChatError('Không kết nối được tới dịch vụ AI, vui lòng thử lại.')
        except anthropic.APIStatusError as e:
            log.error('Chatbot API lỗi %s: %s (request-id %s)', e.status_code, e.message,
                      e.response.headers.get('request-id'))
            raise ChatError('Trợ lý gặp sự cố, vui lòng thử lại sau.')

        if response.stop_reason == 'refusal':
            return 'Xin lỗi, mình không thể hỗ trợ yêu cầu này. Bạn có thể hỏi về tài liệu, quy định mượn trả hoặc cách dùng website nhé.'

        if response.stop_reason != 'tool_use':
            text = '\n'.join(b.text for b in response.content if b.type == 'text').strip()
            return text or 'Xin lỗi, mình chưa có câu trả lời. Bạn thử hỏi cách khác nhé.'

        # Gửi lại nguyên phản hồi (kể cả thinking block) cùng kết quả công cụ
        messages.append({'role': 'assistant', 'content': response.content})
        results = []
        for block in response.content:
            if block.type != 'tool_use':
                continue
            try:
                output = _run_tool(block.name, block.input or {}, user)
                results.append({'type': 'tool_result', 'tool_use_id': block.id,
                                'content': json.dumps(output, ensure_ascii=False, default=str)})
            except Exception:
                log.exception('Chatbot: lỗi khi chạy công cụ %s', block.name)
                db.session.rollback()
                results.append({'type': 'tool_result', 'tool_use_id': block.id, 'is_error': True,
                                'content': 'Không truy vấn được dữ liệu, hãy xin lỗi người dùng.'})
        messages.append({'role': 'user', 'content': results})

    return 'Xin lỗi, câu hỏi hơi phức tạp. Bạn thử hỏi ngắn gọn hơn nhé.'
