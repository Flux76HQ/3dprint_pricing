"""Small shared HTTP helpers: errors, the login guard and a tiny rate limiter."""
import time
from collections import defaultdict, deque
from functools import wraps

from flask import current_app, g, jsonify, request


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def pool():
    return current_app.extensions["pool"]


def config():
    return current_app.config["APP_CONFIG"]


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Verwacht een JSON-object.")
    return data


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if getattr(g, "user_id", None) is None:
            raise ApiError(401, "Niet ingelogd.")
        return view(*args, **kwargs)

    return wrapper


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
            raise ApiError(429, "Te veel pogingen. Probeer het later opnieuw.")
        hits.append(now)


def error_response(error: ApiError):
    return jsonify({"error": error.message}), error.status
