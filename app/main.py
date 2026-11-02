import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
import json
import math
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, load_settings
from .gemini import Gemini, public_error
from .store import ChatError, Store


class TextInput(BaseModel):
    text: str = Field(max_length=40000)

    @field_validator('text')
    @classmethod
    def no_nulls(cls, value):
        if '\x00' in value:
            raise ValueError('Nội dung chứa ký tự không hợp lệ.')
        return value


def event(kind, **data):
    return f'event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def create_app(settings=None, provider=None):
    settings = settings or load_settings()
    store = Store(settings.database)
    backend = provider or (Gemini(settings) if settings.ready else None)
    stops = {}
    token_cache = OrderedDict()
    count_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for stop in stops.values():
            stop.set()
        if backend:
            await backend.close()

    app = FastAPI(title='OLP Chat · Local', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])

    @app.middleware('http')
    async def local_only(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': 'Chỉ chấp nhận yêu cầu cùng ứng dụng local.'}, status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': 'Yêu cầu khác nguồn bị chặn.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ChatError)
    async def chat_error(request, exc):
        return JSONResponse({'detail': exc.message}, status_code=exc.status)

    async def count(text):
        if not text:
            return 0
        # Debounced by frontend; serialize/cache duplicate counts to protect free quota.
        async with count_lock:
            if text in token_cache:
                token_cache.move_to_end(text)
                return token_cache[text]
            result = await backend.count(text)
            token_cache[text] = result
            if len(token_cache) > 128:
                token_cache.popitem(last=False)
            return result

    def require_backend():
        if backend is None:
            raise ChatError(503, 'Chưa cấu hình API. Điền .env và xác nhận project chưa bật billing, rồi khởi động lại.')

    @app.get('/api/config')
    async def config():
        return dict(model=settings.model, budget=settings.budget, ready=backend is not None,
                    has_key=bool(settings.api_key), free_tier_confirmed=settings.free_tier_confirmed,
                    thinking='minimal', prompt_type='Mô phỏng OLP',
                    budget_policy='Tin nhắn mới + output (gồm thinking); không trừ lại lịch sử và system prompt.')

    @app.get('/api/chats')
    async def chats():
        return store.list()

    @app.post('/api/chats', status_code=201)
    async def new_chat():
        return store.create(settings.budget, settings.system_prompt)

    @app.get('/api/chats/{chat_id}')
    async def get_chat(chat_id: str):
        return store.get(chat_id)

    @app.post('/api/tokens')
    async def tokens(body: TextInput):
        if not body.text:
            return dict(tokens=0, exact=True)
        if not backend:
            return dict(tokens=math.ceil(len(body.text.encode('utf-8')) / 4), exact=False,
                        note='Ước lượng khi chưa cấu hình API; không dùng để trừ ngân sách.')
        try:
            return dict(tokens=await count(body.text), exact=True)
        except Exception as exc:
            return JSONResponse({'detail': public_error(exc)}, status_code=502)

    @app.post('/api/chats/{chat_id}/stop')
    async def stop_chat(chat_id: str):
        store.get(chat_id, messages=False)
        if chat_id in stops:
            stops[chat_id].set()
        return {'ok': True}

    @app.post('/api/chats/{chat_id}/messages')
    async def send(chat_id: str, body: TextInput, request: Request):
        require_backend()
        if not body.text.strip():
            raise ChatError(422, 'Hãy nhập nội dung trước khi gửi.')
        # Validate chat before doing a count request.
        chat = store.get(chat_id, messages=False)
        if chat['active'] or not chat['remaining']:
            raise ChatError(409, 'Chat đang sinh hoặc đã hết token. Hãy dừng hoặc tạo chat mới.')
        try:
            input_tokens = await count(body.text)
        except Exception as exc:
            return JSONResponse({'detail': public_error(exc)}, status_code=502)
        turn = store.reserve(chat_id, body.text, input_tokens)
        stop = asyncio.Event()
        stops[chat_id] = stop

        async def generate():
            text = ''
            used = None
            finish = None
            status = 'complete'
            uncertain = False
            refundable_error = False
            stream = None
            next_chunk = None
            stop_task = None
            error_message = None
            started = False
            try:
                yield event('start', input_tokens=input_tokens,
                            remaining=turn['allowance'], max_output_tokens=turn['allowance'])
                if turn['allowance'] == 0:
                    used, status = 0, 'budget'
                else:
                    stream = backend.stream(turn['history'], body.text, turn['allowance'], turn['prompt'])
                    stop_task = asyncio.create_task(stop.wait())
                    while True:
                        if stop.is_set() or await request.is_disconnected():
                            status, uncertain = 'stopped', True
                            break
                        next_chunk = asyncio.create_task(anext(stream))
                        done, _ = await asyncio.wait([next_chunk, stop_task], return_when=asyncio.FIRST_COMPLETED)
                        if stop_task in done:
                            status, uncertain = 'stopped', True
                            break
                        try:
                            chunk = next_chunk.result()
                        except StopAsyncIteration:
                            break
                        started = True
                        text += chunk.text
                        if chunk.output_tokens is not None:
                            used = max(used or 0, chunk.output_tokens)
                        finish = chunk.finish or finish
                        store.checkpoint(turn['reply_id'], text)
                        if chunk.text:
                            yield event('delta', text=chunk.text)
                        if used is not None:
                            yield event('usage', remaining=max(0, turn['allowance'] - used))
                        if (used is not None and used >= turn['allowance']) or finish == 'MAX_TOKENS':
                            used, status = turn['allowance'], 'budget'
                            break
            except asyncio.CancelledError:
                status, uncertain = 'stopped', True
                raise
            except Exception as exc:
                status = 'error'
                # Explicit rejection: generation never began. A timeout/network loss
                # may hide already-generated output, even before its first chunk.
                refundable_error = not started and getattr(exc, 'code', None) in (400, 401, 403, 404, 429)
                uncertain = not refundable_error
                error_message = public_error(exc)
            finally:
                # Cancel the pending read and close upstream, not just browser animation.
                if next_chunk and not next_chunk.done():
                    next_chunk.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await next_chunk
                if stop_task:
                    stop_task.cancel()
                if stream:
                    with suppress(Exception, asyncio.CancelledError):
                        await stream.aclose()
                if status == 'error' and refundable_error:
                    store.rollback(chat_id, turn)
                else:
                    if uncertain or used is None:
                        used = turn['allowance']
                        uncertain = turn['allowance'] > 0
                    store.finish(chat_id, turn, text, used, status)
                stops.pop(chat_id, None)
            if error_message:
                yield event('error', message=error_message)
            yield event('done', chat=store.get(chat_id), status=status, uncertain=uncertain,
                        finish_reason=finish)

        return StreamingResponse(generate(), media_type='text/event-stream', headers={
            'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
        })

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/')
    async def index():
        return FileResponse(ROOT / 'static' / 'index.html')

    return app


app = create_app()
