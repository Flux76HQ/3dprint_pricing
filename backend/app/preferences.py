"""Preferences: what belongs to a person, and what belongs to the business.

A person keeps their own language, theme, notification windows and so on (`users.preferences`). The company details on an invoice,
the VAT rate and rounding that new orders start from and the low-stock thresholds are the business's, shared by everybody
(`shared_preferences`, one row) and changed by an administrator only. The screens and `GET /api/preferences` see both as one
document, so a client does not need to know where a key is kept.
"""
import json

SHARED = ("business", "vat_pct", "price_rounding", "low_stock")


def split(prefs: dict) -> tuple[dict, dict]:
    """(personal, shared) halves of a preferences document."""
    return ({k: v for k, v in prefs.items() if k not in SHARED}, {k: v for k, v in prefs.items() if k in SHARED})


def shared(conn) -> dict:
    row = conn.execute("SELECT preferences FROM shared_preferences").fetchone()
    return row["preferences"] if row else {}


def load(conn, user_id) -> dict:
    """The person's own preferences with the business's on top."""
    row = conn.execute("SELECT preferences FROM users WHERE id = %s", (user_id,)).fetchone()
    return {**((row or {}).get("preferences") or {}), **shared(conn)}


def merge_shared(conn, change: dict) -> None:
    if change:
        conn.execute("INSERT INTO shared_preferences (id, preferences) VALUES (true, %s::jsonb) "
                     "ON CONFLICT (id) DO UPDATE SET preferences = shared_preferences.preferences || EXCLUDED.preferences, updated_at = now()",
                     (json.dumps(change),))


def replace_shared(conn, prefs: dict) -> None:
    conn.execute("INSERT INTO shared_preferences (id, preferences) VALUES (true, %s::jsonb) "
                 "ON CONFLICT (id) DO UPDATE SET preferences = EXCLUDED.preferences, updated_at = now()", (json.dumps(prefs),))
