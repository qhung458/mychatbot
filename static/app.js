const $ = id => document.getElementById(id);
const paths = {
  plus:'M12 5v14M5 12h14', search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  close:'m6 6 12 12M6 18 18 6', menu:'M4 6h16M4 12h16M4 18h16',
  settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M10 2h4l1 3 3 1 3 3-1 3 1 3-3 3-3 1-1 3h-4l-1-3-3-1-3-3 1-3-1-3 3-3 3-1z',
  target:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 1v4M12 19v4M1 12h4M19 12h4',
  tokens:'m12 3 9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 16l9 5 9-5',
  image:'M4 3h16v18H4zM4 16l5-5 5 5 3-3 3 3M15 7h.01',
  chart:'M4 3v18h17M8 16v-4M13 16V6M18 16V9',
  terminal:'M3 4h18v16H3zM7 9l3 3-3 3M13 15h4',
  spark:'m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8L12 3z',
  arrow:'M5 12h14m-5-5 5 5-5 5', shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3zM8 12l3 3 5-6',
  code:'m8 6-6 6 6 6M16 6l6 6-6 6m-3-14-2 16', send:'m21 3-7 18-4-7-7-4 18-7zM10 14 21 3',
  chat:'M21 11a8 8 0 0 1-8 8H8l-5 3V11a9 9 0 0 1 18 0z', alert:'m12 3 10 18H2L12 3zM12 9v5M12 18h.01',
};
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'})) svg.setAttribute(key, value);
  const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', paths[name] || paths.chat); svg.append(path); return svg;
}
document.querySelectorAll('[data-icon]').forEach(el => el.replaceChildren(icon(el.dataset.icon)));
const state = {config:null, chats:[], chat:null, busy:false, draftTokens:0, countExact:false, draftVersion:0, countController:null};
const format = n => new Intl.NumberFormat('vi-VN').format(n);
let draftTimer, toastTimer;

async function api(url, body, signal) {
  const response = await fetch(url, {method:body === undefined ? 'GET' : 'POST', headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body), signal});
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(typeof result.detail === 'string' ? result.detail : 'Không thể thực hiện yêu cầu. Hãy thử lại.');
  }
  return response.json();
}
function toast(text) {
  $('toast').textContent = text; $('toast').hidden = false; clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3800);
}
function notice(text, error = false) {
  $('notice').textContent = text; $('notice').hidden = !text; $('notice').classList.toggle('error', error);
}
function setRemaining(value) {
  $('remaining').textContent = format(value);
  $('budgetFill').style.width = `${Math.max(0, Math.min(100, value / 20))}%`;
  $('budgetBox').classList.toggle('empty', value === 0);
}
function updateControls() {
  const remaining = state.chat?.remaining ?? 2000;
  const empty = remaining === 0 && !state.busy;
  $('sendButton').hidden = state.busy;
  $('stopButton').hidden = !state.busy;
  $('sendButton').disabled = !state.config?.ready || empty || !$('messageInput').value.trim() || (state.countExact && state.draftTokens > remaining);
  $('messageInput').disabled = state.busy || empty;
  $('newChat').disabled = state.busy;
  $('messageInput').placeholder = empty ? 'Chat đã hết token. Tạo cuộc trò chuyện mới để tiếp tục.' : 'Mô tả bài toán, dán code hoặc hỏi về thuật toán…';
}
function renderDraft(tokens, exact, loading = false) {
  state.draftTokens = tokens; state.countExact = exact;
  const label = $('draftCount'); label.replaceChildren(document.createTextNode('Đã dùng: '));
  const strong = document.createElement('strong'); strong.textContent = `${exact ? '' : '≈ '}${format(tokens)}`;
  label.append(strong, document.createTextNode(` token trong ô nhập${loading ? ' · đang đếm…' : ''}`));
  label.classList.toggle('over-budget', tokens > (state.chat?.remaining ?? 2000));
  label.title = exact ? 'Số token từ API Gemini. Chưa gửi thì chưa trừ ngân sách.' : 'Ước lượng, không dùng để trừ ngân sách. Khi gửi, backend đếm bằng API Gemini.';
  updateControls();
}
function draftChanged() {
  const text = $('messageInput').value;
  $('messageInput').style.height = 'auto'; $('messageInput').style.height = `${Math.min($('messageInput').scrollHeight, 180)}px`;
  const version = ++state.draftVersion;
  state.countController?.abort(); clearTimeout(draftTimer);
  if (!text) { renderDraft(0, true); return; }
  renderDraft(Math.ceil(new TextEncoder().encode(text).length / 4), false, !!state.config?.ready);
  if (!state.config?.ready) return;
  draftTimer = setTimeout(async () => {
    state.countController = new AbortController();
    try {
      const result = await api('/api/tokens', {text}, state.countController.signal);
      if (version === state.draftVersion) renderDraft(result.tokens, result.exact);
    } catch (error) {
      if (error.name !== 'AbortError' && version === state.draftVersion) {
        renderDraft(state.draftTokens, false); $('draftCount').title = error.message;
      }
    }
  }, 900);
}
function closeSidebar() { $('sidebar').classList.remove('open'); }
function renderChats() {
  const query = $('search').value.toLocaleLowerCase('vi');
  const matches = state.chats.filter(c => c.title.toLocaleLowerCase('vi').includes(query));
  $('chatCount').textContent = state.chats.length;
  $('chatList').replaceChildren();
  if (!matches.length) {
    const empty = document.createElement('div'); empty.className = 'history-empty'; empty.append(icon('chat'));
    empty.append(document.createTextNode(query ? 'Không tìm thấy hội thoại' : 'Chưa có hội thoại nào'));
    $('chatList').append(empty);
  }
  for (const chat of matches) {
    const button = document.createElement('button'); button.className = `chat-item${chat.id === state.chat?.id ? ' selected' : ''}`;
    button.disabled = state.busy; button.append(icon('chat')); button.title = chat.title;
    const content = document.createElement('span'); content.className = 'chat-item-content';
    const title = document.createElement('span'); title.className = 'chat-item-title'; title.textContent = chat.title;
    const date = document.createElement('span'); date.className = 'chat-item-date';
    date.textContent = `${new Date(chat.created_at).toLocaleDateString('vi-VN', {day:'2-digit',month:'2-digit'})} · ${chat.remaining === 0 ? 'Đã hết token' : `${format(chat.remaining)} token còn lại`}`;
    content.append(title, date); button.append(content);
    if (chat.id === state.chat?.id) button.setAttribute('aria-current', 'page');
    button.addEventListener('click', () => openChat(chat.id)); $('chatList').append(button);
  }
}
function makeMessage(role, text, status = 'complete') {
  const article = document.createElement('article'); article.className = `message ${role}`;
  const avatar = document.createElement('div'); avatar.className = 'message-avatar';
  if (role === 'model') { const img = document.createElement('img'); img.src = '/static/logo.svg'; img.alt = ''; avatar.append(img); }
  else avatar.textContent = 'BẠN';
  const body = document.createElement('div'); body.className = 'message-body';
  const heading = document.createElement('div'); heading.className = 'message-heading'; heading.textContent = role === 'model' ? 'Olympic AI' : 'Bạn';
  const sub = document.createElement('span'); sub.textContent = role === 'model' ? 'Gemini 3.5 Flash-Lite' : ''; heading.append(sub);
  const content = document.createElement('div'); content.className = 'message-text';
  if (role === 'model') content.append(renderMarkdown(text)); else content.textContent = text;
  body.append(heading, content); article.append(avatar, body);
  const notes = {budget:'Đã hết token — phản hồi dừng tại giới hạn.', stopped:'Đã dừng sinh theo yêu cầu.', interrupted:'Phản hồi bị gián đoạn khi server dừng.', error:'Phản hồi bị gián đoạn do lỗi kết nối.'};
  if (notes[status]) { const note = document.createElement('div'); note.className = 'message-state'; note.append(icon('alert'), document.createTextNode(notes[status])); body.append(note); }
  return {article, content};
}
function renderMessages() {
  const messages = state.chat?.messages || [];
  $('welcome').hidden = messages.length > 0; $('messages').hidden = messages.length === 0;
  $('messages').replaceChildren(...messages.map(m => makeMessage(m.role, m.text, m.status).article));
  setRemaining(state.chat?.remaining ?? 2000); updateControls();
  $('conversation').scrollTop = $('conversation').scrollHeight;
}
async function refreshChats() { state.chats = await api('/api/chats'); renderChats(); }
async function openChat(id) {
  if (state.busy) return;
  try {
    state.chat = await api(`/api/chats/${id}`); localStorage.setItem('olp-active-chat', id);
    notice(''); renderChats(); renderMessages(); closeSidebar();
    if (state.chat.active) notice('Chat đang sinh ở một cửa sổ khác. Tải lại sau khi hoàn tất.');
  } catch (error) { toast(error.message); }
}
async function newChat() {
  if (state.busy) return;
  try {
    const chat = await api('/api/chats', {}); state.chat = chat;
    localStorage.setItem('olp-active-chat', chat.id); $('messageInput').value = ''; draftChanged();
    notice(''); await refreshChats(); renderMessages(); closeSidebar(); $('messageInput').focus();
  } catch (error) { toast(error.message); }
}
async function consumeSSE(response, onEvent) {
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  try {
    while (true) {
      const {value, done} = await reader.read(); buffer += decoder.decode(value, {stream:!done});
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        let kind = 'message'; const data = [];
        for (const line of block.split('\n')) {
          if (line.startsWith('event: ')) kind = line.slice(7);
          if (line.startsWith('data: ')) data.push(line.slice(6));
        }
        if (data.length) onEvent(kind, JSON.parse(data.join('\n')));
      }
      if (done) break;
    }
  } finally { reader.releaseLock(); }
}
$('chatForm').addEventListener('submit', async e => {
  e.preventDefault();
  const text = $('messageInput').value;
  if (state.busy || !text.trim() || !state.config?.ready) return;
  if (!state.chat) { await newChat(); $('messageInput').value = text; }
  if (!state.chat) return;
  const chatId = state.chat.id;
  state.busy = true; notice(''); updateControls(); renderChats();
  let accepted = false, replyText = '', completed = false, reply;
  try {
    const response = await fetch(`/api/chats/${chatId}/messages`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text})});
    if (!response.ok) { const result = await response.json(); throw new Error(result.detail || 'Không thể gửi tin nhắn.'); }
    await consumeSSE(response, (kind, data) => {
      if (kind === 'start') {
        accepted = true; $('messageInput').value = ''; draftChanged();
        $('welcome').hidden = true; $('messages').hidden = false;
        $('messages').append(makeMessage('user', text).article);
        reply = makeMessage('model', ''); reply.content.classList.add('streaming-cursor');
        reply.content.textContent = 'Đang suy nghĩ…'; $('messages').append(reply.article);
        setRemaining(data.remaining);
      } else if (kind === 'delta') {
        const nearBottom = $('conversation').scrollHeight - $('conversation').scrollTop - $('conversation').clientHeight < 120;
        replyText += data.text; reply.content.replaceChildren(renderMarkdown(replyText));
        if (nearBottom) $('conversation').scrollTop = $('conversation').scrollHeight;
      } else if (kind === 'usage') setRemaining(data.remaining);
      else if (kind === 'error') notice(data.message, true);
      else if (kind === 'done') {
        completed = true; state.chat = data.chat;
        if (data.uncertain) notice('Phản hồi đã dừng nhưng chưa có usage cuối. Phần output giữ chỗ được tính hết để bảo toàn giới hạn.');
        else if (data.status === 'budget') notice('Chat đã hết 2.000 token. Tạo cuộc trò chuyện mới để tiếp tục.');
      }
    });
    if (!completed) throw new Error('Kết nối bị gián đoạn. Đang cập nhật lại trạng thái chat.');
  } catch (error) {
    notice(error.message, true);
    if (!accepted) { $('messageInput').value = text; draftChanged(); }
    try { state.chat = await api(`/api/chats/${chatId}`); } catch { /* Keep existing visible content. */ }
  } finally {
    state.busy = false; $('stopButton').disabled = false; $('stopButton').textContent = 'Dừng';
    renderMessages(); draftChanged(); refreshChats().catch(() => {});
    if (state.chat?.remaining) $('messageInput').focus();
  }
});
$('stopButton').addEventListener('click', async () => {
  $('stopButton').disabled = true; $('stopButton').textContent = 'Đang dừng…';
  try { await api(`/api/chats/${state.chat.id}/stop`, {}); }
  catch (error) { toast(error.message); $('stopButton').disabled = false; }
});
$('messageInput').addEventListener('input', draftChanged);
$('messageInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!$('sendButton').disabled) $('chatForm').requestSubmit(); }
});
$('newChat').addEventListener('click', newChat);
$('search').addEventListener('input', renderChats);
$('menuButton').addEventListener('click', () => $('sidebar').classList.add('open'));
$('closeSidebar').addEventListener('click', closeSidebar);
$('sidebarOverlay').addEventListener('click', closeSidebar);
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
  if (state.busy || state.chat?.remaining === 0) return;
  $('messageInput').value = button.dataset.prompt; draftChanged(); $('messageInput').focus();
}));
$('settingsButton').addEventListener('click', () => $('settingsDialog').showModal());
$('closeSettings').addEventListener('click', () => $('settingsDialog').close());
$('doneSettings').addEventListener('click', () => $('settingsDialog').close());
$('settingsDialog').addEventListener('click', e => { if (e.target === $('settingsDialog') && e.offsetX >= $('settingsDialog').clientWidth) $('settingsDialog').close(); });
async function boot() {
  try {
    state.config = await api('/api/config');
    $('connectionDot').classList.toggle('ready', state.config.ready);
    $('connectionLabel').textContent = state.config.ready ? 'API đã cấu hình · Free Tier xác nhận' : 'Chưa cấu hình Gemini API';
    $('settingsStatus').textContent = state.config.ready ? 'Đã có API key và xác nhận Free Tier. Chưa gửi yêu cầu sinh nào khi bạn chỉ mở trang.' : 'Giao diện đã sẵn sàng. Cần cấu hình API để đếm token chính xác và trò chuyện với Gemini.';
    await refreshChats();
    const active = localStorage.getItem('olp-active-chat');
    if (active && state.chats.some(c => c.id === active)) await openChat(active);
    else renderMessages();
    renderDraft(0, true);
  } catch { notice('Không kết nối được server local. Kiểm tra cửa sổ terminal rồi tải lại trang.', true); }
}
boot();
