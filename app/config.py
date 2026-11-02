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

    @property
    def ready(self) -> bool:
        return bool(self.api_key and self.free_tier_confirmed)


def load_settings() -> Settings:
    load_dotenv(ROOT / '.env')
    return Settings(
        api_key=os.getenv('GEMINI_API_KEY', '').strip(),
        free_tier_confirmed=os.getenv('GEMINI_FREE_TIER_CONFIRMED', '').lower() == 'true',
        system_prompt=(ROOT / 'system_prompt.txt').read_text(encoding='utf-8').strip(),
    )
