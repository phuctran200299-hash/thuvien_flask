"""Tiện ích: lưu file upload an toàn, phân trang, bộ lọc hiển thị cho Jinja2."""
import io
import secrets
import zipfile
from pathlib import Path
from urllib.parse import urlencode

from flask import current_app, request


class UploadError(Exception):
    pass


# ================================================
# NHẬN DIỆN FILE THEO CHỮ KÝ BYTE (magic number)
# ================================================
def _detect_type(head, data):
    """Trả về (mime, đuôi file) dựa trên nội dung thật của file, None nếu không hỗ trợ."""
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg', 'jpg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png', 'png'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif', 'gif'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp', 'webp'
    if head.startswith(b'%PDF-'):
        return 'application/pdf', 'pdf'
    if head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        return 'application/msword', 'doc'
    if head.startswith(b'PK\x03\x04'):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return None
        if 'mimetype' in names and any(n.startswith('META-INF/') for n in names):
            return 'application/epub+zip', 'epub'
        if any(n.startswith('word/') for n in names):
            return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'docx'
        return None
    if b'\x00' not in data[:4096]:
        try:
            data[:4096].decode('utf-8')
            return 'text/plain', 'txt'
        except UnicodeDecodeError:
            return None
    return None


IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
DOCUMENT_TYPES = {'application/pdf', 'application/epub+zip', 'application/msword', 'text/plain',
                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


def save_upload(file_storage, kind):
    """Lưu file upload. kind: 'image' (ảnh bìa) hoặc 'document' (tài liệu số).
    Trả về dict(filename, mime, size). Ném UploadError nếu không hợp lệ."""
    if not file_storage or not file_storage.filename:
        raise UploadError('Không có file được tải lên')
    data = file_storage.read()
    cfg = current_app.config
    max_size = cfg['MAX_IMAGE_SIZE'] if kind == 'image' else cfg['MAX_DOCUMENT_SIZE']
    if len(data) > max_size:
        raise UploadError(f'File quá lớn (tối đa {format_filesize(max_size)})')
    if not data:
        raise UploadError('File rỗng')

    detected = _detect_type(data[:16], data)
    allowed = IMAGE_TYPES if kind == 'image' else DOCUMENT_TYPES
    if not detected or detected[0] not in allowed:
        raise UploadError('Định dạng file không được hỗ trợ')

    mime, ext = detected
    folder = Path(cfg['UPLOAD_FOLDER'] if kind == 'image' else cfg['DOCUMENT_FOLDER'])
    folder.mkdir(parents=True, exist_ok=True)
    filename = f'{secrets.token_hex(12)}.{ext}'  # tên ngẫu nhiên, không dùng tên người dùng gửi
    (folder / filename).write_bytes(data)
    return {'filename': filename, 'mime': mime, 'size': len(data)}


def delete_upload(filename, kind):
    if not filename or filename.startswith(('http://', 'https://')):
        return
    folder = Path(current_app.config['UPLOAD_FOLDER'] if kind == 'image' else current_app.config['DOCUMENT_FOLDER'])
    path = folder / Path(filename).name
    if path.is_file():
        path.unlink()


# ================================================
# PHÂN TRANG
# ================================================
def page_url(page):
    """URL của trang hiện tại với tham số page mới (giữ nguyên các bộ lọc)."""
    args = request.args.to_dict(flat=False)
    args['page'] = [str(page)]
    return f'{request.path}?{urlencode(args, doseq=True)}'


def get_page():
    try:
        return max(1, int(request.args.get('page', 1)))
    except ValueError:
        return 1


# ================================================
# BỘ LỌC JINJA2
# ================================================
def format_money(value):
    return f'{int(value or 0):,}đ'.replace(',', '.')


def format_date(value, fmt='%d/%m/%Y'):
    return value.strftime(fmt) if value else ''


def format_datetime(value, fmt='%d/%m/%Y %H:%M'):
    return value.strftime(fmt) if value else ''


def format_filesize(size):
    size = int(size or 0)
    if size >= 1048576:
        return f'{size / 1048576:.1f} MB'
    if size >= 1024:
        return f'{size / 1024:.1f} KB'
    return f'{size} B'


def initials(name):
    parts = (name or '').split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return (name or '')[:2].upper()
