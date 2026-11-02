"""The only outbound service. No automatic fallback, search, tools or paid tier switch."""
from dataclasses import dataclass
from google import genai
from google.genai import types


@dataclass
class Chunk:
    text: str = ''
    output_tokens: int | None = None
    finish: str | None = None


class Gemini:
    def __init__(self, settings):
        self.model = settings.model
        self.client = genai.Client(
            api_key=settings.api_key,
            http_options=types.HttpOptions(
                timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )

    async def count(self, text):
        result = await self.client.aio.models.count_tokens(model=self.model, contents=text)
        if result.total_tokens is None:
            raise RuntimeError('Missing token count')
        return result.total_tokens

    def generation_config(self, allowance, prompt):
        return types.GenerateContentConfig(
            system_instruction=prompt,
            max_output_tokens=allowance,
            candidate_count=1,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )

    async def stream(self, history, text, allowance, prompt):
        contents = [types.Content(role=r['role'], parts=[types.Part(text=r['text'])]) for r in history]
        contents.append(types.Content(role='user', parts=[types.Part(text=text)]))
        stream = await self.client.aio.models.generate_content_stream(
            model=self.model, contents=contents,
            config=self.generation_config(allowance, prompt),
        )
        try:
            async for response in stream:
                text_parts = []
                finish = None
                for candidate in response.candidates or []:
                    if candidate.content:
                        for part in candidate.content.parts or []:
                            if part.text and not part.thought:
                                text_parts.append(part.text)
                    if candidate.finish_reason:
                        finish = candidate.finish_reason.value
                usage = response.usage_metadata
                used = None
                if usage is not None:
                    # Output budget includes private thinking, not re-sent prompt/history.
                    used = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                yield Chunk(text=''.join(text_parts), output_tokens=used, finish=finish)
        finally:
            await stream.aclose()

    async def close(self):
        await self.client.aio.aclose()


def public_error(error):
    """Do not put provider error bodies (possibly request text/key) into UI/logs."""
    code = getattr(error, 'code', None)
    if code == 429:
        return 'Hết hạn mức miễn phí hoặc gửi quá nhanh. Hãy thử lại sau; ứng dụng không chuyển gói trả phí.'
    if code in (401, 403):
        return 'API key không hợp lệ hoặc project chưa được phép dùng model. Kiểm tra Google AI Studio.'
    if code == 404:
        return 'Model chưa khả dụng với API key này. Ứng dụng không tự đổi sang model khác.'
    if code == 400:
        return 'Gemini từ chối cấu hình/nội dung yêu cầu. Kiểm tra model và phiên bản SDK theo README.'
    return 'Không nhận được phản hồi Gemini. Kiểm tra Internet và thử lại sau.'
