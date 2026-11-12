"""Small shared HTTP helpers: errors, the login guard and a tiny rate limiter."""
import gzip
import threading
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


# For a signed-in person's own browser only (`private`: never a proxy in between), and without asking again (`immutable`).
KEEP_FOREVER = "private, max-age=31536000, immutable"


def keep_forever(response):
    """Mark an API answer as one the browser may keep: its bytes can never change under this URL (a stored picture, addressed by its id).
    Everything else under /api/ is `no-store`, which `create_app` sets after the handler; this is the one way past that, so a new use
    needs the same certainty. The answer still needed a session to get, but a kept copy can be shown without one, on that device."""
    g.keep_forever = True
    return response


GZIP_FROM = 1024                     # bytes; below this the saving is not worth the header
GZIP_LEVEL = 4                       # measured on the list of 300 calculations (385 kB): 19 kB in 1.8 ms; level 9 saves 3 kB more for twice the time


def compressed(response):
    """A JSON answer, gzipped for a browser that says it reads gzip. Nothing in front of the app is certain to do it (the app also runs
    without a proxy), and a list is mostly repeated keys. Files are not touched: the app's own are compressed once (static_files.py), and
    a download (a backup, a model, a picture) is compressed already or streamed."""
    if (response.status_code != 200 or response.mimetype != "application/json" or response.direct_passthrough
            or "Content-Encoding" in response.headers or "Content-Disposition" in response.headers       # (a backup as JSON is a download)
            or "gzip" not in request.accept_encodings):
        return response
    body = response.get_data()
    if len(body) < GZIP_FROM:
        return response
    response.set_data(gzip.compress(body, compresslevel=GZIP_LEVEL))
    response.headers["Content-Encoding"] = "gzip"
    response.vary.add("Accept-Encoding")
    return response


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
        self._lock = threading.Lock()                # a worker's threads share it: without the lock two attempts at once could both be let through

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self.hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise ApiError(429, "err.rate_limited")
            hits.append(now)


def error_response(error: ApiError):
    if request.path.startswith("/api/v1"):
        # For another application (public_api.py): the reason as a key that does not change with the language, next to the sentence for a person,
        # and when to come back after too many requests.
        response = jsonify({"error": error.message, "code": error.msg.key})
        if error.status == 429:
            response.headers["Retry-After"] = "60"
        return response, error.status
    return jsonify({"error": error.message}), error.status
