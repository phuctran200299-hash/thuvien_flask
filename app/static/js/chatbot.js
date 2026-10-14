/* Widget trợ lý AI: giữ lịch sử trong sessionStorage, gửi lên /api/chat, hiển thị bằng textContent (chống XSS). */
(function () {
  const root = document.getElementById('chatbot');
  if (!root) return;

  const panel = document.getElementById('chatbot-panel');
  const toggle = document.getElementById('chatbot-toggle');
  const list = document.getElementById('chatbot-messages');
  const form = document.getElementById('chatbot-form');
  const input = document.getElementById('chatbot-input');
  const send = document.getElementById('chatbot-send');
  const suggestions = document.getElementById('chatbot-suggestions');
  const STORE_KEY = 'thuvien-chat';
  const name = root.dataset.user;
  const greeting = `Xin chào${name ? ' ' + name : ''}! Mình là trợ lý của thư viện. Bạn cần tìm tài liệu, hỏi quy định mượn trả hay cách dùng website?`;

  let history = load();
  let busy = false;

  function load() {
    try { return JSON.parse(sessionStorage.getItem(STORE_KEY) || '[]'); } catch (e) { return []; }
  }
  function save() {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(history.slice(-30))); } catch (e) { /* bỏ qua */ }
  }

  // Biến đường dẫn nội bộ (/books/12, /my-books...) thành liên kết; phần còn lại là văn bản thuần
  function renderText(el, text) {
    const re = /(\/(?:books\/\d+|books|my-books|notifications|profile|login|register)\b)/g;
    let last = 0, m;
    while ((m = re.exec(text)) !== null) {
      el.appendChild(document.createTextNode(text.slice(last, m.index)));
      const a = document.createElement('a');
      a.href = m[1];
      a.textContent = m[1].startsWith('/books/') ? 'Xem sách ↗' : m[1];
      a.className = 'font-semibold text-indigo-600 underline underline-offset-2 hover:text-indigo-800';
      el.appendChild(a);
      last = re.lastIndex;
    }
    el.appendChild(document.createTextNode(text.slice(last)));
  }

  function bubble(role, text, extra) {
    const row = document.createElement('div');
    row.className = 'flex ' + (role === 'user' ? 'justify-end' : 'justify-start');
    const b = document.createElement('div');
    b.className = 'max-w-[85%] px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words rounded-2xl ' +
      (role === 'user'
        ? 'bg-gradient-to-br from-violet-500 to-indigo-700 text-white rounded-br-md shadow-md shadow-indigo-500/20'
        : 'bg-white text-slate-800 rounded-bl-md ring-1 ring-slate-200 shadow-sm') + (extra ? ' ' + extra : '');
    if (role === 'user') b.textContent = text; else renderText(b, text);
    row.appendChild(b);
    list.appendChild(row);
    list.scrollTop = list.scrollHeight;
    return row;
  }

  function typing() {
    const row = document.createElement('div');
    row.className = 'flex justify-start';
    row.innerHTML = '<div class="px-4 py-3 bg-white rounded-2xl rounded-bl-md ring-1 ring-slate-200 flex gap-1" aria-label="Đang trả lời">' +
      '<span class="w-2 h-2 rounded-full bg-indigo-400 animate-bounce"></span>' +
      '<span class="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:.15s]"></span>' +
      '<span class="w-2 h-2 rounded-full bg-indigo-400 animate-bounce [animation-delay:.3s]"></span></div>';
    list.appendChild(row);
    list.scrollTop = list.scrollHeight;
    return row;
  }

  function renderAll() {
    list.textContent = '';
    bubble('assistant', greeting);
    history.forEach(m => bubble(m.role, m.content));
    suggestions.hidden = history.length > 0;
  }

  const contacts = document.getElementById('contact-buttons');

  function open(show) {
    panel.hidden = !show;
    if (contacts) contacts.hidden = show;  // ẩn nút Gọi/Zalo khi khung chat đang mở
    toggle.setAttribute('aria-expanded', String(show));
    if (show) { list.scrollTop = list.scrollHeight; input.focus(); }
  }

  async function ask(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; send.disabled = true; suggestions.hidden = true;
    history.push({ role: 'user', content: text });
    save();
    bubble('user', text);
    input.value = ''; input.style.height = '';
    const dots = typing();
    try {
      const res = await fetch(root.dataset.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': root.dataset.csrf },
        body: JSON.stringify({ messages: history }),
      });
      const data = await res.json().catch(() => ({}));
      dots.remove();
      if (res.ok && data.reply) {
        history.push({ role: 'assistant', content: data.reply });
        save();
        bubble('assistant', data.reply);
      } else {
        // Câu hỏi lỗi không giữ trong lịch sử để người dùng hỏi lại
        history.pop(); save();
        bubble('assistant', data.error || 'Có lỗi xảy ra, vui lòng tải lại trang và thử lại.', '!bg-rose-50 !text-rose-700 !ring-rose-200');
      }
    } catch (e) {
      dots.remove();
      history.pop(); save();
      bubble('assistant', 'Không kết nối được máy chủ, vui lòng thử lại.', '!bg-rose-50 !text-rose-700 !ring-rose-200');
    } finally {
      busy = false; send.disabled = false; input.focus();
    }
  }

  toggle.addEventListener('click', () => open(panel.hidden));
  document.getElementById('chatbot-close').addEventListener('click', () => open(false));
  document.getElementById('chatbot-reset').addEventListener('click', () => { history = []; save(); renderAll(); input.focus(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !panel.hidden) open(false); });
  form.addEventListener('submit', e => { e.preventDefault(); ask(input.value); });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
  });
  input.addEventListener('input', () => { input.style.height = ''; input.style.height = Math.min(input.scrollHeight, 128) + 'px'; });
  suggestions.querySelectorAll('.chatbot-suggest').forEach(b => b.addEventListener('click', () => ask(b.textContent)));

  renderAll();
})();
