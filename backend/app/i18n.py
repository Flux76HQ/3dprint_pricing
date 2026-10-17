"""Server-side messages, in the language of the screen that asked.

Texts live in lang/<code>.json (flat keys, {name} placeholders; `key_one` / `key_other` when a count `n`
is given), never in the code. Code raises `ApiError(status, "key", name=value)`; the words are chosen when
the answer is written, from the `X-Lang` header the app sends, else the signed-in user's saved language,
else Accept-Language, else Dutch. A key that has no text is shown as it is, so a gap is visible, not blank.
"""
import json
from pathlib import Path

from flask import current_app, g, has_request_context, request

LANGUAGES = ("nl", "en")
DEFAULT_LANGUAGE = "nl"
_DIR = Path(__file__).parent / "lang"
_CATALOGS = {code: json.loads((_DIR / f"{code}.json").read_text(encoding="utf-8")) for code in LANGUAGES}


class L:
    """A message key with its parameters, translated only when it is finally shown (labels, reasons)."""

    def __init__(self, key: str, /, **params):
        self.key, self.params = key, params

    def __str__(self) -> str:
        return translate(DEFAULT_LANGUAGE, self.key, **self.params)


class Localized(ValueError):
    """An error whose words are chosen later. `str()` gives the default language, for logs and tests."""

    def __init__(self, key: str, /, **params):
        self.msg = L(key, **params)
        super().__init__(str(self.msg))


def translate(lang: str, key: str, /, **params) -> str:
    catalog = _CATALOGS.get(lang) or _CATALOGS[DEFAULT_LANGUAGE]
    text = None
    if isinstance(params.get("n"), (int, float)):
        text = catalog.get(f"{key}_{'one' if params['n'] == 1 else 'other'}")
    if text is None:
        text = catalog.get(key)
    if text is None:
        text = _CATALOGS[DEFAULT_LANGUAGE].get(key)
    if text is None:
        return key                                            # no text for this key: show the key itself
    values = {name: (render(value, lang) if isinstance(value, (L, Localized)) else value) for name, value in params.items()}
    try:
        return text.format_map(values)
    except (KeyError, IndexError, ValueError):
        return text


def render(message, lang: str) -> str:
    if isinstance(message, Localized):
        message = message.msg
    if isinstance(message, L):
        return translate(lang, message.key, **message.params)
    return translate(lang, str(message))


def _supported(value):
    code = str(value or "").strip().lower().split("-")[0]
    return code if code in LANGUAGES else None


def _accept_language(header: str):
    for part in (header or "").split(","):
        code = _supported(part.split(";")[0])
        if code:
            return code
    return None


def user_language(user_id, pool=None):
    """The language saved with the account, if any (also used where there is no request: notifications)."""
    try:
        with (pool or current_app.extensions["pool"]).connection() as conn:
            row = conn.execute("SELECT preferences->>'language' AS lang FROM users WHERE id = %s", (user_id,)).fetchone()
    except Exception:
        return None
    return _supported(row["lang"]) if row else None


def request_language() -> str:
    if not has_request_context():
        return DEFAULT_LANGUAGE
    cached = g.get("_language")
    if cached:
        return cached
    lang = _supported(request.headers.get("X-Lang"))
    if not lang and g.get("user_id") is not None:
        lang = user_language(g.user_id)
    lang = lang or _accept_language(request.headers.get("Accept-Language")) or DEFAULT_LANGUAGE
    g._language = lang
    return lang


def tr(key: str, /, **params) -> str:
    return translate(request_language(), key, **params)
