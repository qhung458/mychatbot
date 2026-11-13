from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    api_key: str = ''
    free_tier_confirmed: bool = False
    database: Path = ROOT / 'data' / 'chat.sqlite3'
    model: str = 'gemini-3.5-flash-lite'
    budget: int = 2000
    system_prompt: str = ''
    daily_request_limit: int | None = None

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.free_tier_confirmed)


def load_settings() -> Settings:
    load_dotenv(ROOT / '.env')
    limit = os.getenv('GEMINI_DAILY_REQUEST_LIMIT', '').strip()
    daily_request_limit = int(limit) if len(limit) <= 9 and limit.isascii() and limit.isdecimal() else 0
    return Settings(
        api_key=os.getenv('GEMINI_API_KEY', '').strip(),
        free_tier_confirmed=os.getenv('GEMINI_FREE_TIER_CONFIRMED', '').lower() == 'true',
        system_prompt=(ROOT / 'system_prompt.txt').read_text(encoding='utf-8').strip(),
        daily_request_limit=daily_request_limit or None,
    )
