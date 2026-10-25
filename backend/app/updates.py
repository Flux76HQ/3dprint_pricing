"""The update check: tell the owner that a newer release exists. It announces; it never updates, restarts or downloads anything.

Follows App-Guidance `shared/guidelines/update-check.md`. The latest published, non-prerelease release of this repository is read
from the redirect of `https://github.com/<repo>/releases/latest`, not from api.github.com (60 anonymous requests an hour per IP
address, which a shared server runs out of). The request carries a fixed User-Agent and nothing about the installation. The answer
is remembered in memory (per worker) so a page view never calls GitHub: six hours after a success, ten minutes after a failure, and
"check now" is held to a floor of 30 seconds. A failure keeps the last good answer. It can be switched off with
`PRINTPRICING_UPDATE_CHECK=false`.
"""
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask import Blueprint, current_app, jsonify

from .http import login_required

REPO = "Flux76HQ/3dprint_pricing"
USER_AGENT = "3dprint-pricing-update-check"
TIMEOUT = 5
SUCCESS_TTL = 6 * 3600
FAILURE_TTL = 10 * 60
CHECK_NOW_FLOOR = 30

bp = Blueprint("updates", __name__, url_prefix="/api/update")

_TAG = re.compile(r"/releases/tag/v?(\d+(?:\.\d+){0,3})$")
_NO_RELEASE = re.compile(r"/releases/?$")


ERROR_KEYS = ("rate_limit", "ssl", "timeout", "connection", "unexpected")        # each has a sentence `release.err.<key>` in frontend/lang


class CheckError(Exception):
    """`key` names the cause (the screens have a sentence for each), `detail` is the technical part (an HTTP status, an exception name)."""

    def __init__(self, key: str, detail: str = ""):
        super().__init__(f"{key} {detail}".strip())
        self.key, self.detail = key, detail


def parse(version: str) -> tuple[int, ...] | None:
    """`1.10.0` -> (1, 10, 0); anything that is not dotted numbers (a `v` in front is fine) -> None."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (version or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(latest: str, current: str) -> bool:
    """Numerically, part by part, the shorter one padded with zeros (1.10.0 is newer than 1.9.0, 2.1 equals 2.1.0). A string that does not parse is not newer."""
    a, b = parse(latest), parse(current)
    if a is None or b is None:
        return False
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)) > b + (0,) * (size - len(b))


def release_url(version: str) -> str:
    """Built from the repository and the version, never taken from GitHub's answer, so the screen cannot be made to point elsewhere."""
    return f"https://github.com/{REPO}/releases/tag/v{version}" if parse(version) else ""


def fetch_latest() -> str:
    """The latest release number, or "" when the repository has none (or is not visible). Raises CheckError for everything else."""
    try:
        res = requests.get(f"https://github.com/{REPO}/releases/latest", timeout=TIMEOUT, allow_redirects=False,
                           headers={"User-Agent": USER_AGENT})
    except requests.exceptions.SSLError:
        raise CheckError("ssl", "SSLError") from None
    except requests.exceptions.Timeout:
        raise CheckError("timeout", "Timeout") from None
    except requests.exceptions.ConnectionError:
        raise CheckError("connection", "ConnectionError") from None
    except requests.RequestException as exc:
        raise CheckError("unexpected", type(exc).__name__) from None
    if res.status_code in (301, 302, 303, 307, 308):
        where = urlparse(res.headers.get("Location", ""))
        path = where.path
        if (where.scheme or "https") != "https" or (where.hostname or "github.com") != "github.com":
            raise CheckError("unexpected", f"redirect to {where.hostname or where.scheme or 'nothing'}")
        if tag := _TAG.search(path):
            return tag.group(1)
        if _NO_RELEASE.search(path):
            return ""
        raise CheckError("unexpected", f"redirect to {path[:80] or 'nothing'}")
    if res.status_code == 404:
        return ""
    if res.status_code in (403, 429):
        raise CheckError("rate_limit", f"HTTP {res.status_code}")
    raise CheckError("unexpected", f"HTTP {res.status_code}")


class Checker:
    """One per app. The lock makes concurrent requests share one call to GitHub."""

    def __init__(self, current: str, enabled: bool = True, fetch=None, clock=time.monotonic):
        self.current, self.enabled = current, enabled
        self._fetch, self._clock = fetch or fetch_latest, clock
        self._lock = threading.Lock()
        self._latest = ""
        self._error: CheckError | None = None
        self._at: float | None = None                    # monotonic time of the last attempt
        self._checked_at: str | None = None              # the same moment, for the screen

    def status(self, force: bool = False) -> dict:
        with self._lock:
            if self.enabled:
                age = float("inf") if self._at is None else self._clock() - self._at
                if age >= (CHECK_NOW_FLOOR if force else FAILURE_TTL if self._error else SUCCESS_TTL):
                    self._refresh()
            return self._snapshot()

    def _refresh(self) -> None:
        try:
            self._latest, self._error = self._fetch(), None
        except CheckError as exc:                        # keep the last good answer, add the reason
            self._error = exc
            current_app.logger.warning("Update check failed: %s", exc)
        except Exception as exc:                         # a GitHub outage, or a bug here, never becomes an error page
            self._error = CheckError("unexpected", type(exc).__name__)
            current_app.logger.warning("Update check failed: %s", exc)
        self._at = self._clock()
        self._checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _snapshot(self) -> dict:
        shown = self._latest if self.enabled else ""
        return {
            "enabled": self.enabled, "current": self.current, "latest": shown,
            "available": is_newer(shown, self.current), "url": release_url(shown),
            "checkedAt": self._checked_at if self.enabled else None,
            "error": self._error.key if self.enabled and self._error else None,
            "errorDetail": self._error.detail if self.enabled and self._error else "",
            "repo": REPO,
        }


def _checker() -> Checker:
    return current_app.extensions["update_checker"]


# The app has one owner, so being signed in is being the administrator (AGENTS.md: single tenant).
@bp.get("")
@login_required
def get_status():
    return jsonify(_checker().status())


@bp.post("/check")
@login_required
def check_now():
    return jsonify(_checker().status(force=True))
