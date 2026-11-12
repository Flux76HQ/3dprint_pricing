"""Configuration, read once from the environment.

Every value that differs per deployment lives in `.env` (see `.env.example`);
nothing here is a secret default except where the app refuses to start without
one.
"""
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigError(RuntimeError):
    pass


# The database is one file in the host's DATA_PATH (the container sees DATA_PATH as /data).
DEFAULT_DATABASE_PATH = "/data/db/printpricing.sqlite3"
# Where the automatic backups are kept (auto_backup.py): next to the copies scripts/update.sh makes, outside UPLOAD_DIR, so a factory reset leaves them.
# deploy/entrypoint.sh creates it and hands it to the app's user.
DEFAULT_BACKUP_DIR = "/data/backups/auto"


# Where "Sync" in Settings -> Filaments reads the shared filament library from: a JSON file as the app exports it.
DEFAULT_LIBRARY_URL = "https://raw.githubusercontent.com/Flux76HQ/3dprint_pricing/main/library/filaments.json"
LIBRARY_HOSTS = ("raw.githubusercontent.com", "gist.githubusercontent.com")
# Where "Bijdragen" opens GitHub (the app adds the issue form for the language: `05-filament-library.yml` or `nl-05-...`; a workflow turns the issue into a pull request). Only offered while the source above is the default one.
CONTRIBUTE_URL = "https://github.com/Flux76HQ/3dprint_pricing/issues/new"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Environment variable {name} is required (see .env.example).")
    return value


def _flag(name: str) -> bool:
    """A switch in .env: only TRUE (any case), 1 or yes turns it on; empty, unset or anything else is off."""
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


def _switch(name: str, default: bool = True) -> bool:
    """A switch that is on unless .env turns it off: false, 0, no or off (any case) is off; empty, unset or anything else keeps the default."""
    value = os.environ.get(name, "").strip().lower()
    if value in ("false", "0", "no", "off"):
        return False
    return True if value in ("true", "1", "yes", "on") else default


@dataclass(frozen=True)
class Config:
    database_path: str
    session_secret: str
    setup_code: str
    rp_id: str
    rp_name: str
    rp_origins: tuple[str, ...]
    session_hours: int
    cookie_secure: bool
    static_dir: str
    upload_dir: str = "/data/uploads"
    backup_dir: str = DEFAULT_BACKUP_DIR
    max_upload_mb: int = 50
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    ai_images_enabled: bool = False
    filament_library_url: str = DEFAULT_LIBRARY_URL
    spoolman_url: str = ""
    haspelsync_url: str = ""
    haspelsync_api_key: str = ""
    update_check: bool = True
    legacy_database_url: str = ""

    @property
    def push_configured(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


def image_tag() -> str:
    """The image tag of this installation (PRINTPRICING_TAG: latest, beta, 0.26.15, ...), the same value as in docker-compose.yml."""
    return os.environ.get("PRINTPRICING_TAG", "").strip()


def build_channel() -> str:
    """"beta" when the tag names a beta build, otherwise "stable"."""
    return "beta" if "beta" in image_tag().lower() else "stable"


def _library_url() -> str:
    """The address of the shared library; empty switches the sync off. Only https on a GitHub raw host: the server fetches it, so it is
    never taken from a request, and a typo here must not turn the app into a way to reach other machines."""
    url = os.environ.get("FILAMENT_LIBRARY_URL", DEFAULT_LIBRARY_URL).strip()
    if url and (not url.startswith("https://") or (urlparse(url).hostname or "") not in LIBRARY_HOSTS):
        raise ConfigError(f"FILAMENT_LIBRARY_URL must be an https address on {' or '.join(LIBRARY_HOSTS)}, or empty.")
    return url


def _http_address(value: str, name: str, example: str) -> str:
    """The address of a service on the own network, tidied: empty means there is none. Plain http is allowed (a home network runs these on it);
    a trailing slash, a query and a login in the address are not (a path is: the service can sit under one), because the app adds the paths
    itself. `name` and `example` only word the refusal."""
    url = value.strip().rstrip("/")
    if not url:
        return ""
    try:
        parts = urlparse(url)
        port = parts.port
    except ValueError:
        raise ConfigError(f"{name} must be an http(s) address such as {example}.") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or port == 0 or len(url) > 200):
        raise ConfigError(f"{name} must be an http(s) address such as {example} (no login, query or fragment), or empty.")
    return url


def check_spoolman_url(value: str) -> str:
    """A Spoolman address, tidied: empty means there is none. Used for `SPOOLMAN_URL` and for the address an administrator types in the app,
    so both are held to the same rule."""
    return _http_address(value, "SPOOLMAN_URL", "http://spoolman:8000")


def _spoolman_url() -> str:
    """`SPOOLMAN_URL` from .env; empty (the default) means that the address, if any, is the one typed in the app."""
    return check_spoolman_url(os.environ.get("SPOOLMAN_URL", ""))


def check_haspelsync_url(value: str) -> str:
    """A HaspelSync address, tidied: empty means there is none. Used for `HASPELSYNC_URL` and for the address an administrator types in the app."""
    return _http_address(value, "HASPELSYNC_URL", "http://haspelsync:4000")


def _haspelsync_url() -> str:
    """`HASPELSYNC_URL` from .env; empty (the default) means that the address, if any, is the one typed in the app."""
    return check_haspelsync_url(os.environ.get("HASPELSYNC_URL", ""))


# What HaspelSync hands out as an API key: `ams_` and the base64url of 32 random bytes. The length is a range so that a longer key later still passes;
# what matters is that nothing but a token can reach a header (no space, no line break).
HASPELSYNC_KEY = re.compile(r"^ams_[A-Za-z0-9_-]{20,128}$")


def check_haspelsync_key(value: str) -> str:
    """A HaspelSync API key, tidied: empty means there is none. Used for `HASPELSYNC_API_KEY` and for the key an administrator types in the app."""
    key = value.strip()
    if key and not HASPELSYNC_KEY.match(key):
        raise ConfigError("HASPELSYNC_API_KEY must be an API key from HaspelSync (it starts with ams_), or empty.")
    return key


def _haspelsync_key() -> str:
    """`HASPELSYNC_API_KEY` from .env; empty (the default) means that the key, if any, is the one typed in the app."""
    return check_haspelsync_key(os.environ.get("HASPELSYNC_API_KEY", ""))


def _legacy_database_url() -> str:
    """The PostgreSQL of the releases before SQLite, to be imported once: `LEGACY_DATABASE_URL`. A docker-compose.yml from before the switch still sets
    `DATABASE_URL` to that address (nothing else reads that name any more), and an installation whose compose file was never replaced keeps working."""
    url = os.environ.get("LEGACY_DATABASE_URL", "").strip()
    old = os.environ.get("DATABASE_URL", "").strip()
    return url or (old if old.startswith(("postgresql://", "postgres://")) else "")


def load_config() -> Config:
    # RP_ID and RP_ORIGINS are optional: empty means "the address the app is opened on" (relying_party.py).
    origins = tuple(o.strip().rstrip("/") for o in os.environ.get("RP_ORIGINS", "").split(",") if o.strip())
    rp_id = os.environ.get("RP_ID", "").strip().lower()
    if "://" in rp_id or "/" in rp_id or ":" in rp_id:
        raise ConfigError("RP_ID must be a domain name only, without https://, a path or a port (for example print.example.com).")
    secret = _required("SESSION_SECRET")
    if len(secret) < 32:
        raise ConfigError("SESSION_SECRET must be at least 32 characters (generate: openssl rand -hex 32).")
    haspelsync_url, haspelsync_key = _haspelsync_url(), _haspelsync_key()
    if haspelsync_key and not haspelsync_url:
        # A key from .env must not be sendable to an address someone types in the app later: it goes to the address .env names, and nowhere else.
        raise ConfigError("HASPELSYNC_API_KEY needs HASPELSYNC_URL: a key set in .env is only sent to the address set in .env.")
    return Config(
        database_path=os.environ.get("DATABASE_PATH", "").strip() or DEFAULT_DATABASE_PATH,
        session_secret=secret,
        setup_code=_required("SETUP_CODE"),
        rp_id=rp_id,
        rp_name=os.environ.get("RP_NAME", "3D Print Pricing"),
        rp_origins=origins,
        session_hours=int(os.environ.get("SESSION_HOURS", "24")),
        cookie_secure=bool(origins) and all(o.startswith("https://") for o in origins),   # unpinned: decided per request
        static_dir=os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static")),
        upload_dir=os.environ.get("UPLOAD_DIR", "/data/uploads"),
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "50")),
        vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", "").strip(),
        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", "").strip(),
        vapid_subject=os.environ.get("VAPID_SUBJECT", "").strip() or f"mailto:admin@{rp_id or 'localhost'}",
        ai_images_enabled=_flag("AI_IMAGES_ENABLED"),
        filament_library_url=_library_url(),
        spoolman_url=_spoolman_url(),
        haspelsync_url=haspelsync_url,
        haspelsync_api_key=haspelsync_key,
        update_check=_switch("PRINTPRICING_UPDATE_CHECK"),
        legacy_database_url=_legacy_database_url(),
    )
