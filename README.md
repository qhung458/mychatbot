# OLP Chat — web luyện tập local

FastAPI + HTML/CSS/JavaScript, SQLite, Google Gen AI SDK. Giao diện tham khảo ảnh hệ thống thi,
nhưng đây là **bản luyện tập**, không phải sản phẩm chính thức của BTC.

## Chạy trên Windows

Python 3.11+; không cần Node.js, GPU hay database server. Mở PowerShell tại repo:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Điền `.env` bằng trình soạn thảo, không đưa key vào chat hoặc Git:

```dotenv
GEMINI_API_KEY=YOUR_KEY_HERE
GEMINI_FREE_TIER_CONFIRMED=false
```

1. Tạo key tại [Google AI Studio](https://aistudio.google.com/api-keys).
2. Kiểm tra project của key **chưa liên kết billing**, có quyền Free Tier cho `gemini-3.5-flash-lite`.
3. Khi đã tự xác nhận, đổi `GEMINI_FREE_TIER_CONFIRMED=true`. Đây chỉ là xác nhận của người dùng,
   **không phải xác minh billing tự động**. API key không cung cấp cho ứng dụng quyền kiểm tra điều này.
4. Chạy:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Hoặc `powershell -ExecutionPolicy Bypass -File .\start.ps1`. Mở **http://127.0.0.1:8000**.
Ctrl+C trong terminal để dừng. Khởi động lại sau khi đổi `.env` hoặc system prompt.
Không chạy nhiều worker hoặc nhiều server dùng chung file SQLite; bản local dùng một process.

Không có key vẫn mở được giao diện, tạo/mở/tìm chat. Nút Gửi bị khóa; bộ đếm ô nhập có dấu `≈`
và chỉ là ước lượng UTF-8, không phải token Gemini. Không có phản hồi AI giả.

## Quy tắc 2.000 token

Mỗi chat mới có **2.000 token** và lịch sử rỗng:

```text
còn lại = 2.000 − tổng token tin nhắn mới − tổng output (gồm thinking)
```

- **Ô trên:** ngân sách còn lại của chat đang chọn.
- **Dưới ô nhập:** token của nội dung đang soạn; chưa gửi thì chưa trừ. Khi có API, gọi `count_tokens`
  sau khi dừng gõ 900 ms, cache tối đa 128 nội dung. Lỗi đếm thì hiện `≈`; backend phải đếm chính xác
  trước khi chấp nhận gửi, không tin con số từ trình duyệt.
- Lịch sử cũ được gửi lại cho Gemini để giữ ngữ cảnh, **không trừ lại vào quỹ luyện tập**.
  Lượng token Google tính cho một API request khác với quỹ này.
- System prompt được lưu riêng cho từng chat tại lúc tạo, **không trừ vào quỹ 2.000**.
  Đây là quy tắc mô phỏng, chưa xác minh BTC có tính system prompt/thinking như vậy không.
- Ví dụ: gửi 300 token, model dùng 500 output token → còn 1.200. Lượt sau gửi 200 →
  `max_output_tokens=1000`; không gửi yêu cầu sinh với hạn mức lớn hơn rồi mới cắt giao diện.
- Backend giữ chỗ toàn bộ phần output còn lại, chống gửi song song hoặc gửi lặp để vượt ngân sách.
- `max_output_tokens` được truyền trực tiếp cho Gemini trước lúc sinh. Khi nhận `MAX_TOKENS` hoặc
  usage đạt giới hạn, đóng stream. Phản hồi có thể dừng giữa câu/code; hết token thì khóa chat.
- Chỉ gửi input vừa đúng số còn lại: input được lưu, quỹ về 0, **không gọi sinh**.
  Input vượt số còn lại: từ chối, không trừ token, giữ lại nội dung đang soạn.
- Dùng `thinking_level=MINIMAL` (được model hỗ trợ). Minimal không đồng nghĩa hoàn toàn không thinking.
  Output usage cộng `candidates_token_count` và `thoughts_token_count`, không cộng lịch sử/system.
- Số output thực tế thường chỉ có trong metadata cuối. Trong khi đang sinh, số còn lại cập nhật khi API
  cung cấp metadata; không tự coi số ký tự là token chính xác.

### Dừng giữa chừng, mất kết nối, khởi động lại

Nút **Dừng** gửi yêu cầu về backend: hủy tác vụ đọc đang chờ và đóng stream upstream, không chỉ ngừng
hiệu ứng chữ trên màn hình. Việc hủy kết nối không có nghĩa ta biết chính xác thời điểm máy chủ Google
dừng xử lý. Giới hạn cứng vẫn do `max_output_tokens` trên yêu cầu ban đầu đảm nhiệm.

Nếu dừng/ngắt mạng trước khi có usage cuối, ứng dụng **tính hết phần output đã giữ chỗ** để không hoàn nhầm
token mà phía Google có thể đã sinh. Khi server bị tắt đột ngột, giữ nguyên reservation đã trừ và đánh dấu
phản hồi gián đoạn khi mở lại. UI giải thích trường hợp này. Khi có usage cuối bình thường, hoàn phần chưa dùng.

## Chi phí

Mã nguồn, giao diện local, SQLite và framework không thu phí hosting/license để chạy bản này.
Gemini được gọi qua Internet. Google quyết định quota và điều kiện Free Tier, ứng dụng không bảo đảm
miễn phí với một key thuộc project đã bật billing. Không có mua gói, bật billing, model fallback,
search grounding, code execution, hay tự thử lại request sinh khi lỗi.

Khi Free Tier hết quota, hiển thị lỗi và dừng. Khi chỉ mở giao diện, không gọi sinh nội dung.
Việc đếm token khi soạn cũng gọi API và có thể chịu rate limit; có debounce và cache để giảm lượt gọi.

## Cấu trúc

```text
app/
  config.py       # Đọc .env, model và ngân sách
  store.py        # SQLite, reservation và số dư; không tin dữ liệu từ UI
  gemini.py       # Adapter gọi/count/stream Gemini, cấu hình output cap
  main.py         # HTTP API, SSE, điều phối stream và Stop
static/
  index.html      # Sidebar, chat, composer, hộp thiết lập
  style.css       # Giao diện responsive, không tải font/CDN
  app.js          # UI, bộ đếm draft, SSE, lịch sử
  markdown.js     # Render Markdown an toàn bằng DOM, code fence + copy
system_prompt.txt # Prompt mô phỏng; sửa file rồi tạo chat mới
tests/test_chat.py
.env.example
start.ps1
```

Lịch sử trong `data/chat.sqlite3` được lưu trên máy và bị Git bỏ qua. Danh sách chat cũ vẫn xem được,
nhưng khi tạo chat mới không lấy tin nhắn/tóm tắt từ chat khác. Key chỉ dùng phía server, không có API
đọc key hoặc chỉnh billing. Nội dung tin nhắn được gửi tới Google khi dùng Gemini, không hoàn toàn offline.
Raw HTML từ model không được thực thi; không có script/ảnh/CDN bên ngoài trong nội dung chat.
Chỉ nghe `127.0.0.1`; không cấu hình để công khai ra mạng hoặc làm dịch vụ nhiều tài khoản.

## API local

| Endpoint | Chức năng |
|---|---|
| `GET /api/config` | Trạng thái cấu hình không chứa key |
| `GET /api/chats` | Danh sách và số dư |
| `POST /api/chats` | Tạo chat 2.000 token |
| `GET /api/chats/{id}` | Nội dung của một chat |
| `POST /api/tokens` | Đếm `{ "text": "..." }`, không trừ quỹ |
| `POST /api/chats/{id}/messages` | Nhận text và trả SSE `start/delta/usage/error/done` |
| `POST /api/chats/{id}/stop` | Dừng stream đang chạy |

## Kiểm tra

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/app.js
node --check static/markdown.js
```

Test dùng provider giả **chỉ trong tests** để kiểm tra quỹ, cô lập lịch sử, output cap, stop trong khi đang chờ
upstream, quota error, khôi phục SQLite và kiểm tra cấu hình thật của SDK. Không cần key, không phát sinh API usage.
Không dùng kết quả test giả để khẳng định Gemini thật đã kết nối. Chưa có key thì chưa xác nhận live
generation/count_tokens, quyền truy cập model hoặc billing của tài khoản.

Tài liệu: [Gemini model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
[SDK](https://googleapis.github.io/python-genai/), [Thinking](https://ai.google.dev/gemini-api/docs/thinking),
[Pricing](https://ai.google.dev/gemini-api/docs/pricing).
