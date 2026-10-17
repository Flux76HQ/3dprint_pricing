"""Configuration, read once from the environment.

Every value that differs per deployment lives in `.env` (see `.env.example`);
nothing here is a secret default except where the app refuses to start without
one.
"""
import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Environment variable {name} is required (see .env.example).")
    return value


@dataclass(frozen=True)
class Config:
    database_url: str
    session_secret: str
    setup_code: str
    rp_id: str
    rp_name: str
    rp_origins: tuple[str, ...]
    session_hours: int
    cookie_secure: bool
    static_dir: str


def load_config() -> Config:
    origins = tuple(o.strip().rstrip("/") for o in _required("RP_ORIGINS").split(",") if o.strip())
    secret = _required("SESSION_SECRET")
    if len(secret) < 32:
        raise ConfigError("SESSION_SECRET must be at least 32 characters (generate: openssl rand -hex 32).")
    return Config(
        database_url=_required("DATABASE_URL"),
        session_secret=secret,
        setup_code=_required("SETUP_CODE"),
        rp_id=_required("RP_ID"),
        rp_name=os.environ.get("RP_NAME", "3D Print Pricing"),
        rp_origins=origins,
        session_hours=int(os.environ.get("SESSION_HOURS", "24")),
        cookie_secure=all(o.startswith("https://") for o in origins),
        static_dir=os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static")),
    )
