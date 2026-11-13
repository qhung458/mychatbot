"""SQLite owns balances. The browser never supplies trusted token totals/history."""
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo('America/Los_Angeles')


class ChatError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, budget INTEGER NOT NULL,
                    remaining INTEGER NOT NULL CHECK(remaining >= 0),
                    active INTEGER NOT NULL DEFAULT 0, reserved INTEGER NOT NULL DEFAULT 0,
                    system_prompt TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL REFERENCES chats(id), role TEXT NOT NULL,
                    text TEXT NOT NULL, tokens INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'complete'
                );
                CREATE TABLE IF NOT EXISTS api_daily_usage (
                    day TEXT NOT NULL, model TEXT NOT NULL, requests INTEGER NOT NULL,
                    PRIMARY KEY (day, model)
                );
            ''')
            # A killed server cannot know how much an upstream request generated.
            # Reserved tokens stay consumed; do not silently refund uncertain usage.
            db.execute("UPDATE messages SET status='interrupted' WHERE status='streaming'")
            db.execute('UPDATE chats SET active=0, reserved=0 WHERE active=1')

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, budget, prompt):
        chat_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self.db() as db:
            db.execute('INSERT INTO chats VALUES (?,?,?,?,?,?,0,0,?)',
                       (chat_id, 'Cuộc trò chuyện mới', now, now, budget, budget, prompt))
        return self.get(chat_id)

    def record_generation(self, model):
        day = datetime.now(PACIFIC).date().isoformat()
        with self.db() as db:
            db.execute('''INSERT INTO api_daily_usage VALUES (?, ?, 1)
                          ON CONFLICT(day, model) DO UPDATE SET requests = requests + 1''',
                       (day, model))

    def daily_usage(self, model):
        day = datetime.now(PACIFIC).date().isoformat()
        with self.db() as db:
            row = db.execute('SELECT requests FROM api_daily_usage WHERE day=? AND model=?',
                             (day, model)).fetchone()
        return row['requests'] if row else 0

    def get(self, chat_id, messages=True):
        with self.db() as db:
            row = db.execute('SELECT * FROM chats WHERE id=?', (chat_id,)).fetchone()
            if row is None:
                raise ChatError(404, 'Không tìm thấy cuộc trò chuyện.')
            result = dict(row)
            result.pop('system_prompt')
            result.pop('reserved')
            result['active'] = bool(result['active'])
            if messages:
                result['messages'] = [dict(r) for r in db.execute(
                    'SELECT id, role, text, tokens, status FROM messages WHERE chat_id=? ORDER BY id',
                    (chat_id,))]
            return result

    def list(self):
        with self.db() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM chats ORDER BY updated_at DESC')]
        return [self.get(chat_id, messages=False) for chat_id in ids]

    def reserve(self, chat_id, text, input_tokens):
        """Reserve ALL remaining output before starting a request, atomically."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            chat = db.execute('SELECT * FROM chats WHERE id=?', (chat_id,)).fetchone()
            if chat is None:
                raise ChatError(404, 'Không tìm thấy cuộc trò chuyện.')
            if chat['active']:
                raise ChatError(409, 'Chat này đang sinh câu trả lời. Hãy chờ hoặc bấm Dừng.')
            if chat['remaining'] <= 0:
                raise ChatError(409, 'Đã hết token. Hãy tạo cuộc trò chuyện mới.')
            if input_tokens > chat['remaining']:
                raise ChatError(422, 'Nội dung nhập vượt số token còn lại. Hãy rút ngắn hoặc tạo chat mới.')
            previous = [dict(r) for r in db.execute(
                "SELECT role, text FROM messages WHERE chat_id=? AND text != '' ORDER BY id", (chat_id,))]
            allowance = chat['remaining'] - input_tokens
            now = datetime.now(timezone.utc).isoformat()
            title = ' '.join(text.split())[:64] if not previous else chat['title']
            db.execute('UPDATE chats SET remaining=0, active=1, reserved=?, title=?, updated_at=? WHERE id=?',
                       (allowance, title, now, chat_id))
            user_id = db.execute('INSERT INTO messages(chat_id,role,text,tokens) VALUES (?,?,?,?)',
                                 (chat_id, 'user', text, input_tokens)).lastrowid
            reply_id = db.execute("INSERT INTO messages(chat_id,role,text,status) VALUES (?,?,?,'streaming')",
                                  (chat_id, 'model', '')).lastrowid
            return dict(history=previous, prompt=chat['system_prompt'], allowance=allowance,
                        reply_id=reply_id, user_id=user_id, input_tokens=input_tokens)

    def checkpoint(self, reply_id, text):
        with self.db() as db:
            db.execute('UPDATE messages SET text=? WHERE id=?', (text, reply_id))

    def finish(self, chat_id, turn, text, output_tokens, status):
        used = max(0, min(turn['allowance'], output_tokens))
        with self.db() as db:
            db.execute('UPDATE messages SET text=?, tokens=?, status=? WHERE id=?',
                       (text, used, status, turn['reply_id']))
            db.execute('UPDATE chats SET remaining=?, active=0, reserved=0 WHERE id=?',
                       (turn['allowance'] - used, chat_id))

    def rollback(self, chat_id, turn):
        with self.db() as db:
            db.execute('DELETE FROM messages WHERE id IN (?,?)', (turn['user_id'], turn['reply_id']))
            db.execute('UPDATE chats SET remaining=?, active=0, reserved=0 WHERE id=?',
                       (turn['input_tokens'] + turn['allowance'], chat_id))
