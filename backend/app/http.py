"""Small shared HTTP helpers: errors, the login guard and a tiny rate limiter."""
import time
from collections import defaultdict, deque
from functools import wraps

from flask import current_app, g, jsonify, request

from .i18n import L, Localized, render, request_language


class ApiError(Exception):
    """`message` is a key from lang/*.json (or an `L` / `Localized`); its words are chosen when the answer is written."""

    def __init__(self, status: int, message, **params):
        if isinstance(message, Localized):
            message = message.msg
        self.msg = message if isinstance(message, L) else L(message, **params)
        super().__init__(str(self.msg))
        self.status = status

    @property
    def message(self) -> str:
        return render(self.msg, request_language())


def pool():
    return current_app.extensions["pool"]


def config():
    return current_app.config["APP_CONFIG"]


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "err.json_object")
    return data


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if getattr(g, "user_id", None) is None:
            raise ApiError(401, "err.not_logged_in")
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    """Signed in as an administrator; a regular user is refused with 403."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        require_admin()
        return view(*args, **kwargs)

    return wrapper


def require_admin() -> None:
    if getattr(g, "user_id", None) is None:
        raise ApiError(401, "err.not_logged_in")
    if getattr(g, "role", None) != "admin":
        raise ApiError(403, "err.admin_only")


class RateLimiter:
    """In-memory sliding window, per worker. Enough to make guessing the setup code slow."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise ApiError(429, "err.rate_limited")
        hits.append(now)


def error_response(error: ApiError):
    return jsonify({"error": error.message}), error.status
