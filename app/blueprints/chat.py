"""API của trợ lý AI hỏi đáp (widget chat góc dưới bên phải)."""
import time

from flask import Blueprint, current_app, jsonify, request, session
from flask_login import current_user

from ..chatbot import ChatError, ask

bp = Blueprint('chat', __name__)


def _rate_limited():
    """Giới hạn số câu hỏi mỗi phiên trong một khoảng thời gian (chống spam, tiết kiệm chi phí API)."""
    limit, window = current_app.config['CHATBOT_RATE_LIMIT'], current_app.config['CHATBOT_RATE_WINDOW']
    now = time.time()
    recent = [t for t in session.get('chat_times', []) if now - t < window]
    if len(recent) >= limit:
        session['chat_times'] = recent
        return True
    session['chat_times'] = recent + [now]
    return False


@bp.route('/api/chat', methods=['POST'])
def chat():
    if not current_app.config['CHATBOT_ENABLED']:
        return jsonify(error='Trợ lý AI đang tắt.'), 503
    data = request.get_json(silent=True) or {}
    if _rate_limited():
        return jsonify(error='Bạn hỏi hơi nhanh, vui lòng đợi vài phút rồi hỏi tiếp nhé.'), 429
    try:
        reply = ask(data.get('messages'), current_user)
    except ChatError as e:
        return jsonify(error=str(e)), 400
    return jsonify(reply=reply)
