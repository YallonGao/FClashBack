"""Runtime configuration, read from environment variables only.

The server has no config file on purpose: a container or systemd unit can
carry every value, and there is no second place to look when one is wrong.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEV_JWT_SECRET = "dev-insecure-secret-change-me-0123456789abcdef"


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    access_token_minutes: int
    refresh_token_days: int
    max_snapshot_bytes: int
    history_limit: int
    allow_registration: bool
    allow_private_fetch: bool
    data_dir: Path

    @property
    def uses_dev_secret(self) -> bool:
        return self.jwt_secret == DEV_JWT_SECRET


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.getenv("FCLASH_DATA_DIR", str(BASE_DIR / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = os.getenv("FCLASH_DATABASE_URL", "").strip()
    if not database_url:
        database_url = f"sqlite:///{(data_dir / 'fclash.db').as_posix()}"
    return Settings(
        database_url=database_url,
        jwt_secret=os.getenv("FCLASH_JWT_SECRET", DEV_JWT_SECRET),
        jwt_algorithm=os.getenv("FCLASH_JWT_ALGORITHM", "HS256"),
        access_token_minutes=_int("FCLASH_ACCESS_TOKEN_MINUTES", 60 * 24),
        refresh_token_days=_int("FCLASH_REFRESH_TOKEN_DAYS", 180),
        max_snapshot_bytes=_int("FCLASH_MAX_SNAPSHOT_BYTES", 8 * 1024 * 1024),
        history_limit=_int("FCLASH_HISTORY_LIMIT", 20),
        allow_registration=_bool("FCLASH_ALLOW_REGISTRATION", True),
        # Subscription refresh fetches whatever URL the owner stored. Local
        # and link-local targets stay blocked unless someone opts in.
        allow_private_fetch=_bool("FCLASH_ALLOW_PRIVATE_FETCH", False),
        data_dir=data_dir,
    )
