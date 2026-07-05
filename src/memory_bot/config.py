from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    table_name: str
    model: str
    allowed_users: set[int]
    telegram_token: str
    telegram_secret: str = ""
    history_exchanges: int = 10
    voice_max_seconds: int = 120


def load_settings(env: Mapping[str, str]) -> Settings:
    raw_users = env.get("MEMORY_BOT_ALLOWED_USERS", "").strip()
    allowed = {int(p) for p in raw_users.split(",") if p.strip()}
    return Settings(
        table_name=env.get("MEMORY_BOT_TABLE", "notes"),
        model=env.get("MEMORY_BOT_MODEL", "anthropic:claude-sonnet-4-6"),
        allowed_users=allowed,
        telegram_token=env.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_secret=env.get("MEMORY_BOT_WEBHOOK_SECRET", ""),
        history_exchanges=int(env.get("MEMORY_BOT_HISTORY_EXCHANGES", "10")),
        voice_max_seconds=int(env.get("MEMORY_BOT_VOICE_MAX_SECONDS", "120")),
    )
