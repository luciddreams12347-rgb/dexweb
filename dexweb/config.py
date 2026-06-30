import os
from urllib.parse import unquote, urlparse

from .site_config import SITE_CONFIG


def _bool_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_int_env(name):
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return int(value)


def _database_url():
    value = os.environ.get("DATABASE_URL", "").strip()
    return urlparse(value) if value else None


_db_url = _database_url()


class DexwebConfig:
    SECRET_KEY = os.environ.get("APP_SECRET") or os.environ.get("DEX_SECRET_KEY") or "dev-change-me"
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or os.environ.get("DEX_ADMIN_PASSWORD") or "changeme"
    DB_HOST = os.environ.get("DEX_DB_HOST") or (_db_url.hostname if _db_url else None)
    DB_PORT = int(os.environ.get("DEX_DB_PORT") or (_db_url.port if _db_url and _db_url.port else 3306))
    DB_USER = os.environ.get("DEX_DB_USER") or (unquote(_db_url.username) if _db_url and _db_url.username else None)
    DB_PASSWORD = os.environ.get("DEX_DB_PASSWORD") or (unquote(_db_url.password) if _db_url and _db_url.password else None)
    DB_NAME = os.environ.get("DEX_DB_NAME") or (_db_url.path.lstrip("/") if _db_url and _db_url.path else None)
    DB_ENABLED = _bool_env("DEX_DB_ENABLED", bool(_db_url))
    SITE_LOG_PATH = os.environ.get("DEX_SITE_LOG_PATH", "")
    MAX_MESSAGES_PER_ROOM = int(os.environ.get("DEX_MAX_MESSAGES_PER_ROOM", "200"))
    DEX_SYSTEM_PROMPT_PATH = os.environ.get("DEX_SYSTEM_PROMPT_PATH", "")
    DEX_PROVIDER = os.environ.get("DEX_PROVIDER", "local-placeholder")
    DEX_MODEL = os.environ.get("DEX_MODEL", "")
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_CONNECT_TIMEOUT = int(os.environ.get("OLLAMA_CONNECT_TIMEOUT", "10"))
    OLLAMA_GENERATION_TIMEOUT = _optional_int_env("OLLAMA_GENERATION_TIMEOUT")
    OLLAMA_MAX_RETRIES = int(os.environ.get("OLLAMA_MAX_RETRIES", "2"))
    LIBRARY_UPLOADS_DIR = os.environ.get("LIBRARY_UPLOADS_DIR", "")
    LIBRARY_MAX_UPLOAD_BYTES = int(os.environ.get("LIBRARY_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SITE_CONFIG = SITE_CONFIG
