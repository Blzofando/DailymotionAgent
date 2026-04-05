"""
core/config.py — Configuração centralizada do DailymotionAgent.
Carrega e valida todas as variáveis de ambiente no startup.
Qualquer chave obrigatória ausente causa falha imediata (fail-fast).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env da raiz do projeto
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env")


def _require(key: str) -> str:
    """Retorna variável de ambiente ou lança erro claro."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"[CONFIG] Variável obrigatória ausente: '{key}'\n"
            f"         Verifique seu arquivo .env (veja .env.example)"
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    session_name: str
    bot_token: str
    admin_chat_id: int
    source_channel: str


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    key: str


@dataclass(frozen=True)
class DailymotionConfig:
    client_id: str
    client_secret: str
    username: str
    password: str
    max_hours_per_day: float
    max_uploads_per_day: int


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str


@dataclass(frozen=True)
class AgentConfig:
    lookup_window: int
    fuzzy_threshold: int
    mining_limit: int
    fresh_count: int
    hype_count: int
    ffmpeg_path: str
    ffprobe_path: str
    max_duration_sec: int
    max_size_bytes: int


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    supabase: SupabaseConfig
    dailymotion: DailymotionConfig
    gemini: GeminiConfig
    agent: AgentConfig


def load_config() -> AppConfig:
    """Carrega e valida todas as configurações. Lança erro se algo estiver faltando."""

    telegram = TelegramConfig(
        api_id=int(_require("TELEGRAM_API_ID")),
        api_hash=_require("TELEGRAM_API_HASH"),
        session_name=_optional("TELEGRAM_SESSION_NAME", "dailymotion_agent"),
        bot_token=_require("TELEGRAM_BOT_TOKEN"),
        admin_chat_id=int(_require("TELEGRAM_ADMIN_CHAT_ID")),
        source_channel=_optional("TELEGRAM_SOURCE_CHANNEL", "@ProducoesIndependentesAsia"),
    )

    supabase = SupabaseConfig(
        url=_require("SUPABASE_URL"),
        key=_require("SUPABASE_KEY"),
    )

    dailymotion = DailymotionConfig(
        client_id=_require("DAILYMOTION_CLIENT_ID"),
        client_secret=_require("DAILYMOTION_CLIENT_SECRET"),
        username=_require("DAILYMOTION_USERNAME"),
        password=_require("DAILYMOTION_PASSWORD"),
        max_hours_per_day=float(_optional("DM_MAX_HOURS_PER_DAY", "10")),
        max_uploads_per_day=int(_optional("DM_MAX_UPLOADS_PER_DAY", "15")),
    )

    gemini = GeminiConfig(
        api_key=_require("GEMINI_API_KEY"),
    )

    agent = AgentConfig(
        lookup_window=int(_optional("LOOKUP_WINDOW", "10")),
        fuzzy_threshold=int(_optional("FUZZY_THRESHOLD", "82")),
        mining_limit=int(_optional("MINING_LIMIT", "100")),
        fresh_count=int(_optional("FRESH_COUNT", "10")),
        hype_count=int(_optional("HYPE_COUNT", "20")),
        ffmpeg_path=_optional("FFMPEG_PATH", "/usr/bin/ffmpeg"),
        ffprobe_path=_optional("FFPROBE_PATH", "/usr/bin/ffprobe"),
        max_duration_sec=int(_optional("MAX_DURATION_SEC", "7190")),
        max_size_bytes=int(_optional("MAX_SIZE_BYTES", "4080218931")),
    )

    return AppConfig(
        telegram=telegram,
        supabase=supabase,
        dailymotion=dailymotion,
        gemini=gemini,
        agent=agent,
    )


# Singleton — importado por todos os módulos
config: AppConfig = load_config()
