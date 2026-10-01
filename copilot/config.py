"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env support for local runs; real environment variables always win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    # "groq" (free tier, open models) or "anthropic" (Claude, prepaid).
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic").strip().lower())
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("COPILOT_MODEL", "claude-haiku-4-5-20251001"))
    personas_dir: Path = field(default_factory=lambda: Path(os.getenv("PERSONAS_DIR", ROOT / "personas")))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", ROOT / "data")))
    # Extra origins allowed for every persona (e.g. http://localhost:8000 while testing).
    extra_origins: list[str] = field(default_factory=lambda: _list("EXTRA_ALLOWED_ORIGINS"))
    # Abuse and cost controls.
    rate_limit_messages: int = field(default_factory=lambda: _int("RATE_LIMIT_MESSAGES", 20))
    rate_limit_window_seconds: int = field(default_factory=lambda: _int("RATE_LIMIT_WINDOW_SECONDS", 600))
    max_turns_per_session: int = field(default_factory=lambda: _int("MAX_TURNS_PER_SESSION", 30))
    max_message_chars: int = field(default_factory=lambda: _int("MAX_MESSAGE_CHARS", 2000))
    max_history_messages: int = field(default_factory=lambda: _int("MAX_HISTORY_MESSAGES", 20))
    daily_token_budget: int = field(default_factory=lambda: _int("DAILY_TOKEN_BUDGET", 1_500_000))
    # Lead delivery: POSTed as JSON (e.g. a Zapier "Catch Hook" that emails you / writes a Sheet).
    lead_webhook_url: str = field(default_factory=lambda: os.getenv("LEAD_WEBHOOK_URL", ""))
    # Bearer token for the private /v1/leads endpoint.
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", ""))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "copilot.sqlite3"
