"""A notification when a kind of filament is nearly used up.

On a roll the owner chooses "notify me when this is nearly used up". That belongs to the kind, not the roll: rolls with the same
barcode (without one: the same brand, type, material and colour) share it and count together, so three rolls of 1 kg are one
kind with 3 kg. The threshold is set under Settings: one in grams for every kind, optionally another for a material (PLA, PETG...).

After anything that changes the shelf the totals of the watched kinds are compared with their thresholds. A kind that has just
dropped to or below its threshold is announced once; it is announced again only after it has been above the threshold in between
(a new purchase), so adjusting a roll that is already low does not repeat the message. The message goes through the push outbox:
it is delivered by the background worker within a minute, on the usual terms (quiet hours, one message per kind), and saving a
roll never waits for a push service.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from . import push, stock
from .i18n import DEFAULT_LANGUAGE, translate, user_language

log = logging.getLogger(__name__)

KIND = "low_stock"
DEFAULT_THRESHOLD_G = 500
MAX_LISTED = 4                      # a notification is a glance, not a report


def material_key(name) -> str:
    """"PLA", " pla " and "Pla" are one material."""
    return str(name or "").strip().lower()


def _grams(value, fallback: Decimal) -> Decimal:
    try:
        grams = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return fallback
    return grams if grams.is_finite() and grams >= 0 else fallback


def settings(preferences) -> dict:
    """The owner's thresholds as numbers: the default, and the ones of their own per material."""
    stored = (preferences or {}).get("low_stock")
    stored = stored if isinstance(stored, dict) else {}
    default = _grams(stored.get("threshold_g"), Decimal(DEFAULT_THRESHOLD_G))
    own = stored.get("materials") if isinstance(stored.get("materials"), dict) else {}
    return {"default": default, "materials": {material_key(k): _grams(v, default) for k, v in own.items() if material_key(k)}}


def threshold_for(limits: dict, material: str) -> Decimal:
    return limits["materials"].get(material, limits["default"])


def low_kinds(limits: dict, groups: list) -> dict:
    """The watched kinds whose total (all their rolls together) is at or below the threshold, by key."""
    return {g["key"]: g for g in groups
            if g["notify_low"] and Decimal(g["remaining_g"]) <= threshold_for(limits, material_key(g["material"]))}


def kind_name(group: dict) -> str:
    """"Bambu Lab Matte Zwart (PLA)": what the owner calls it; the material only when the name does not already say it."""
    name = " ".join(part for part in (group["brand"], group["product_type"], group["colour"]) if part)
    material = group["material"].strip()
    return f"{name} ({material})" if material and material.lower() not in name.lower() else name


def build_message(lang: str, low: dict) -> tuple:
    """Title and body: the emptiest kinds first, and how many more there are when the list is long."""
    items = sorted(low.values(), key=lambda g: (Decimal(g["remaining_g"]), kind_name(g).lower()))
    shown = ", ".join(f"{kind_name(g)}: {Decimal(g['remaining_g']):.0f} g" for g in items[:MAX_LISTED])
    body = translate(lang, "push.low_body", list=shown)
    if len(items) > MAX_LISTED:
        body += " " + translate(lang, "push.low_more", n=len(items) - MAX_LISTED)
    return translate(lang, "push.low_title"), body


def check(pool, cfg, now: "datetime | None" = None) -> int:
    """Compare the shelf with each person's thresholds and queue a notification for what just ran low. Returns how many
    people were notified. Never raises: a problem here must not turn a saved roll into an error."""
    try:
        return _check(pool, cfg, now or datetime.now(timezone.utc))
    except Exception:
        log.exception("low-stock check failed")
        return 0


def _check(pool, cfg, now) -> int:
    with pool.connection() as conn:
        users = conn.execute("SELECT id, preferences FROM users").fetchall()
        groups = stock.groups(stock.fetch(conn))
    queued = 0
    for user in users:
        low = low_kinds(settings(user["preferences"]), groups)
        keys = list(low)
        with pool.connection() as conn:
            # What is no longer low (or no longer watched, or gone) is forgotten, so the next drop is announced.
            conn.execute("DELETE FROM low_stock_alerts WHERE user_id = %s AND NOT (stock_key = ANY(%s::text[]))", (user["id"], keys))
            # Claimed atomically, so two workers saving at the same moment announce it once.
            fresh = conn.execute("INSERT INTO low_stock_alerts (user_id, stock_key) SELECT %s, unnest(%s::text[]) "
                                 "ON CONFLICT DO NOTHING RETURNING stock_key", (user["id"], keys)).fetchall()
        if fresh and cfg.push_configured:
            lang = user_language(user["id"], pool) or DEFAULT_LANGUAGE
            title, body = build_message(lang, low)               # everything that is low, not only the newest: one message replaces the last
            push.enqueue(pool, user["id"], push.build_payload(KIND, title, body, "/#/filament"), now)
            queued += 1
    return queued
