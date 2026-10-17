"""A notification when a material (PLA, PETG, ...) is nearly used up.

The owner switches it on and sets a threshold in grams: one for every material, optionally another for a
material of their own choosing. After anything that changes what is on the shelf the totals are compared with
those thresholds. A material that has just dropped to or below its threshold is announced once; it is announced
again only after it has been above the threshold in between (a new purchase), so adjusting a roll that is already
low does not repeat the message. The message goes through the push outbox: it is delivered by the background worker
within a minute, on the usual terms (quiet hours, one message per kind), and saving a roll never waits for a push service.

Rolls without a material are not followed: their total mixes unrelated filaments and would say nothing.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from . import push
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


def settings(preferences) -> "dict | None":
    """The owner's thresholds as numbers, or None when the notification is off."""
    stored = (preferences or {}).get("low_stock")
    if not isinstance(stored, dict) or stored.get("enabled") is not True:
        return None
    default = _grams(stored.get("threshold_g"), Decimal(DEFAULT_THRESHOLD_G))
    own = stored.get("materials") if isinstance(stored.get("materials"), dict) else {}
    return {"default": default, "materials": {material_key(k): _grams(v, default) for k, v in own.items() if material_key(k)}}


def threshold_for(config: dict, key: str) -> Decimal:
    return config["materials"].get(key, config["default"])


def totals(conn) -> dict:
    """What is left per material, by lower-case name: {"name", "rolls", "grams"} (archived rolls are not stock)."""
    out: dict[str, dict] = {}
    for row in conn.execute("SELECT material, remaining_g FROM filament_spools WHERE NOT archived").fetchall():
        key = material_key(row["material"])
        if not key:
            continue
        item = out.setdefault(key, {"name": str(row["material"]).strip(), "rolls": 0, "grams": Decimal(0)})
        item["grams"] += row["remaining_g"]
        item["rolls"] += 1 if row["remaining_g"] > 0 else 0
    return out


def low_materials(config: dict, all_totals: dict) -> dict:
    return {key: item for key, item in all_totals.items() if item["grams"] <= threshold_for(config, key)}


def build_message(lang: str, low: dict) -> tuple:
    """Title and body: the emptiest materials first, and how many more there are when the list is long."""
    items = sorted(low.values(), key=lambda item: (item["grams"], item["name"].lower()))
    shown = ", ".join(f"{item['name']}: {item['grams']:.0f} g" for item in items[:MAX_LISTED])
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
        all_totals = totals(conn)
    queued = 0
    for user in users:
        config = settings(user["preferences"])
        with pool.connection() as conn:
            if config is None:                                   # switched off: forget, so switching on starts afresh
                conn.execute("DELETE FROM low_stock_alerts WHERE user_id = %s", (user["id"],))
                continue
            low = low_materials(config, all_totals)
            keys = list(low)
            conn.execute("DELETE FROM low_stock_alerts WHERE user_id = %s AND NOT (material = ANY(%s::text[]))", (user["id"], keys))
            # Claimed atomically, so two workers saving at the same moment announce it once.
            fresh = conn.execute("INSERT INTO low_stock_alerts (user_id, material) SELECT %s, unnest(%s::text[]) "
                                 "ON CONFLICT DO NOTHING RETURNING material", (user["id"], keys)).fetchall()
        if fresh and cfg.push_configured:
            lang = user_language(user["id"], pool) or DEFAULT_LANGUAGE
            title, body = build_message(lang, low)               # everything that is low, not only the newest: one message replaces the last
            push.enqueue(pool, user["id"], push.build_payload(KIND, title, body, "/#/filament"), now)
            queued += 1
    return queued
