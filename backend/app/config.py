"""Configuration, read once from the environment.

Every value that differs per deployment lives in `.env` (see `.env.example`);
nothing here is a secret default except where the app refuses to start without
one.
"""
import os
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigError(RuntimeError):
    pass


# Where "Sync" in Settings -> Filaments reads the shared filament library from: a JSON file as the app exports it.
DEFAULT_LIBRARY_URL = "https://raw.githubusercontent.com/Flux76HQ/3dprint_pricing/main/library/filaments.json"
LIBRARY_HOSTS = ("raw.githubusercontent.com", "gist.githubusercontent.com")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Environment variable {name} is required (see .env.example).")
    return value


def _flag(name: str) -> bool:
    """A switch in .env: only TRUE (any case), 1 or yes turns it on; empty, unset or anything else is off."""
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


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
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 50
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    ai_images_enabled: bool = False
    filament_library_url: str = DEFAULT_LIBRARY_URL

    @property
    def push_configured(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


def _library_url() -> str:
    """The address of the shared library; empty switches the sync off. Only https on a GitHub raw host: the server fetches it, so it is
    never taken from a request, and a typo here must not turn the app into a way to reach other machines."""
    url = os.environ.get("FILAMENT_LIBRARY_URL", DEFAULT_LIBRARY_URL).strip()
    if url and (not url.startswith("https://") or (urlparse(url).hostname or "") not in LIBRARY_HOSTS):
        raise ConfigError(f"FILAMENT_LIBRARY_URL must be an https address on {' or '.join(LIBRARY_HOSTS)}, or empty.")
    return url


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
        upload_dir=os.environ.get("UPLOAD_DIR", "/data/uploads"),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "50")),
        vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", "").strip(),
        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", "").strip(),
        vapid_subject=os.environ.get("VAPID_SUBJECT", "").strip() or f"mailto:admin@{_required('RP_ID')}",
        ai_images_enabled=_flag("AI_IMAGES_ENABLED"),
        filament_library_url=_library_url(),
    )
