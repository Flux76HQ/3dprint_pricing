"""Optional AI product images: a photo of the printed object goes to OpenAI's image model, which puts it in a realistic setting.

Everything here exists only when `AI_IMAGES_ENABLED=TRUE` in .env: the flag is checked on the server for every route (404 when
off), the browser merely follows `ai_images` in /api/auth/status. The OpenAI key is typed under Settings and kept encrypted with a key
derived from SESSION_SECRET (`passwords.seal`); it is never sent back, only its last four characters. Photos and results are kept in the
database (`project_images`, like the invoice logo) and re-encoded on the way in, so nothing from an upload is stored as it came.

A picture takes a while, so asking for pictures only queues them (`ai_image_jobs`); a background thread of this web worker makes them one
by one and writes what happens to `ai_image_log`. The browser polls the jobs, so leaving the page stops nothing. A job whose thread died
(the container restarted) is marked failed once it has not moved for a few minutes.

Pictures are made for a purpose (`PURPOSES`: a marketplace ad, social media, a web shop), four per purpose. The product name, the
specifications and the extra text typed with the calculation (`projects.image_text`) are put on the first of the four by `image_overlay`,
as a poster in a fixed template, never by the model, and only when all three are filled in; the logo of the invoice goes on when its switch is on and
whoever asks has the business mode on.

What a set of pictures cost is kept, not worked out from the picture: OpenAI says how many tokens it counted for each (`usage` in its answer), and that is
written to `ai_image_usage` in the transaction that stores the picture, with the prices and the rate of that moment (`usage_of`, `_record_usage`). The prices
are OpenAI's, in dollars per million tokens, typed under Settings; for a model whose list price is known here (`DEFAULT_PRICES`) none has to be typed. The rate
that turns dollars into euros is always typed: it is nobody's to guess. Money is `Decimal` all the way, and a set is rounded to cents before sets are added, so
the lines on the screen add up to the total (`sets_of`). `GET /api/ai-images/usage` is for administrators, like everything under `/api/ai-images`."""
import base64
import colorsys
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO

import requests
from flask import Blueprint, Response, current_app, g, jsonify, request
from PIL import Image, ImageOps, UnidentifiedImageError

from . import image_overlay, invoice_logo, passwords, preferences
from .api import text
from .db import ForeignKeyViolation
from .http import ApiError, RateLimiter, config, json_body, keep_forever, login_required, pool
from .i18n import L, render, request_language

log = logging.getLogger(__name__)

bp = Blueprint("ai_images", __name__, url_prefix="/api")

KEY_INFO = b"printpricing/ai-key/v1"
OPENAI = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2"
# OpenAI's own list price, Standard tier, in US dollars per million tokens (https://developers.openai.com/api/docs/pricing, read on 2026-11-12). Only a *default*: what an
# administrator typed goes before it, and a model that is not here has none, so no cost is ever worked out from a price nobody checked. When OpenAI changes a price, change it here
# (the pictures made before keep the price they were made at).
DEFAULT_PRICES = {"gpt-image-2": {"text_in": Decimal("5"), "image_in": Decimal("8"), "image_out": Decimal("30")}}
PRICE_KEYS = ("text_in", "image_in", "image_out")
MAX_PRICE = Decimal("100000")        # dollars per million tokens; a typo, not a price, above this
MAX_RATE = Decimal("100")            # euros per dollar
MAX_TOKENS = 10**9                   # one picture; more than this in an answer is not a count
MILLION = Decimal(1_000_000)
CENT = Decimal("0.01")
MAX_SETS = 100                       # sets listed on the screen; the totals count all of them
QUALITIES = ("low", "medium", "high")
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_EDGE = 2048                      # the photo is scaled down to this before it is stored and sent
MAX_GENERATED = 12                   # per calculation; delete some to make more
THUMB_EDGE = 192                     # the cover in the list of calculations is 56 CSS pixels, so this is sharp up to a 3x screen
PHOTO_FORMATS = {"PNG", "JPEG", "MPO", "WEBP"}      # MPO is what some phones write as a JPEG
CONNECT_TIMEOUT, READ_TIMEOUT = 10, 100             # the whole request has to fit in the 120 seconds a proxy in front is asked to allow
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,59}$")
KEY = re.compile(r"^[\x21-\x7e]{20,300}$")           # printable ASCII, no spaces
SECRET_LIKE = re.compile(r"sk-[A-Za-z0-9_\-*.]{4,}")  # what an OpenAI message may quote of a key: never kept
STALE_MINUTES = 5                    # a job that has not moved for this long lost its thread (one picture takes at most ~2 minutes)
LOG_KEEP = 500                       # rows of the log that are kept
# Problems with the key, the account or the photo: the pictures still queued would fail in the same way, so they are given up at once.
ABORT_KEYS = {"ai.err_no_key", "ai.err_key_unreadable", "ai.err_key_invalid", "ai.err_quota", "ai.err_model_unknown", "ai.err_no_photo"}

# variant -> (size sent to the model, shape of the picture, where it is placed). The shapes are the ones shops and social media ask for.
VARIANTS = {
    "square": ("1024x1024", "a square 1:1 picture for a web shop listing",
               "Place the object naturally in a fitting everyday setting."),
    "landscape": ("1536x1024", "a landscape 3:2 picture for a banner or a listing header",
                  "Place the object naturally in a fitting everyday setting with room around it."),
    "portrait": ("1024x1536", "a portrait picture for a marketplace listing or social media",
                 "Place the object naturally in a fitting everyday setting."),
    "studio": ("1024x1024", "a square 1:1 studio picture",
               "Place the object on a plain, light, softly lit surface with a clean neutral background and a soft shadow."),
    "detail": ("1024x1024", "a square 1:1 close-up picture",
               "Show the object from close by so that it fills most of the frame and its details and finish are clearly visible, "
               "in front of a softly blurred fitting background."),
    "context": ("1024x1024", "a square 1:1 picture that shows the object in use",
                "Show the object in use in a fitting everyday setting, from a little further away, so that its size and its "
                "surroundings are clear."),
}
# purpose -> (the four pictures made for it, what the model is told about it). A purpose is also a template of `image_overlay`.
# The first of the four is the poster: the only one that gets the texts. The others stay photos (with the logo, when that is on).
PURPOSES = {
    "marktplaats": (("landscape", "studio", "detail", "square"),
                    "The picture is for a classified ad on an online marketplace: an honest, clear photo such as a careful private seller "
                    "takes at home in daylight, nothing glamourised. "),
    # all four square: they are posted as one carousel, and a carousel shows every picture in the shape of its first
    "social": (("square", "context", "detail", "studio"),
               "The picture is for an advertisement on social media: a lively, eye-catching lifestyle photo with attractive light and colour, "
               "taken from a slightly dynamic camera angle. "),
    "webshop": (("studio", "square", "detail", "landscape"),
                "The picture is a product image for a web shop: clean, professional and evenly lit, with the object as the clear subject. "),
}
assert set(PURPOSES) == set(image_overlay.TEMPLATES) and all(len(p[0]) == 4 and set(p[0]) <= set(VARIANTS) for p in PURPOSES.values())
WARNINGS = ("ai.warn_text_incomplete", "ai.warn_logo_business", "ai.warn_logo_none")
NAME_MAX, SPEC_MAX, SPECS_MAX, EXTRA_MAX = 60, 60, 5, 80          # what fits in the template
SCENE_MAX = 300                                                   # the owner's own words about the setting, added to the prompt
ROOM_FOR_LOGO = "Keep the top left corner calm and uncluttered as well. "
ORIGINS = ("photo", "model")         # what a calculation's pictures are made from: a photo of the object, a picture of its 3D model
# what the model is told it is looking at, per set of pictures it is given
LEAD = {
    ("photo",): "Edit this photo of a 3D-printed object into {shape}. Keep the object itself exactly as it is: same shape, proportions, "
                "colour and visible print layers; do not redesign, restyle or add parts to it.",
    ("model",): "This picture is a plain rendering of the 3D model of an object that is 3D printed. Turn it into {shape} of the real, "
                "printed object: keep its shape and proportions exactly as shown and seen from the same side, in the colour shown, made of "
                "matte plastic with fine horizontal print layers; do not redesign, restyle or add parts to it.",
    ("photo", "model"): "The first picture is a photo of a 3D-printed object; the second is a plain rendering of its 3D model, which shows "
                        "its exact shape, possibly from another side. Make {shape} of the object. Keep the object itself exactly as it is: "
                        "the shape and proportions of the model, the colour, material and visible print layers of the photo; do not "
                        "redesign, restyle or add parts to it.",
}
# with more than one picture of the model: the parts of the object, or the object from several sides
LEAD[("model", "model")] = (
    "These pictures are plain renderings of the 3D model of one object that is 3D printed: its separate parts, or the object seen from "
    "several sides. Turn them into {shape} of the real, printed object, put together as it is meant to be used: keep the shape and "
    "proportions of every part exactly as shown, in the colours shown, made of matte plastic with fine horizontal print layers; do not "
    "redesign, restyle or add parts to it.")
LEAD[("photo", "model", "model")] = (
    "The first picture is a photo of a 3D-printed object; the others are plain renderings of its 3D model, which show the exact shape of "
    "its parts, or of the object from several sides. Make {shape} of the object. Keep the object itself exactly as it is: the shape and "
    "proportions of the model, the colour, material and visible print layers of the photo; do not redesign, restyle or add parts to it.")
MAX_MODEL_VIEWS = 10                 # saved views of the 3D models of one calculation; all of them go to the model with the photo
MODEL_REF = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(:[1-9][0-9]{0,2})?$")


# with more than one photo: the object from several sides, with or without renderings of its model after them
LEAD[("photo", "photo")] = (
    "These pictures are photos of one 3D-printed object, taken from several sides. Make {shape} of that object. Keep the object itself "
    "exactly as it is: same shape, proportions, colour and visible print layers; do not redesign, restyle or add parts to it.")
LEAD[("photo", "photo", "model")] = (
    "The first {photos} pictures are photos of one 3D-printed object, taken from several sides; the rest are plain renderings of its 3D "
    "model, which show its exact shape. Make {shape} of the object. Keep the object itself exactly as it is: the shape and proportions of "
    "the model, the colour, material and visible print layers of the photos; do not redesign, restyle or add parts to it.")
MAX_PHOTOS = 10                      # photos of the object that one calculation keeps
MAX_SELECTED = 6                     # pictures (photos and views together) that go to the image model with one request


def lead(sources: tuple, shape: str) -> str:
    """The opening of the prompt for these pictures (their origins, the photos first): what the model is looking at."""
    photos = sum(1 for origin in sources if origin == "photo")
    models = sum(1 for origin in sources if origin == "model")
    if photos >= 2:
        key = ("photo", "photo") + (("model",) if models else ())
    else:
        key = ("photo",) * photos + ("model",) * min(models, 2)              # two renderings and more read the same
    return LEAD[key].format(shape=shape, photos=photos)


PROMPT = (
    "{lead} {placement} {setting}{purpose}{room}"
    "It must look like a real photograph taken with a camera in natural light: no 3D render, illustration, cartoon or glossy CGI look. "
    "No text, no logos, no watermarks, no people."
)

# at most this many pictures per hour per worker: every one costs money, and nobody but the owner is signed in
_limit = RateLimiter(40, 3600)


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session, and none exists unless the owner switched the feature on in .env."""
    if not config().ai_images_enabled:
        raise ApiError(404, "err.not_found")


COLOUR = re.compile(r"^#[0-9a-f]{6}$")


def colour_name(colour: str) -> str:
    """A plain word for a colour (`#rrggbb`), to go with its code: the model follows "dark green" better than six hex digits."""
    red, green, blue = (int(colour[at:at + 2], 16) / 255 for at in (1, 3, 5))
    hue, light, saturation = colorsys.rgb_to_hls(red, green, blue)
    if saturation < 0.12 or light < 0.06 or light > 0.96:
        return "black" if light < 0.14 else "white" if light > 0.88 else "dark grey" if light < 0.4 else "light grey" if light > 0.66 else "grey"
    degrees = hue * 360
    name = next(word for upto, word in ((15, "red"), (42, "orange"), (68, "yellow"), (165, "green"), (195, "turquoise"), (255, "blue"),
                                        (290, "purple"), (340, "pink"), (361, "red")) if degrees < upto)
    if name == "orange" and light < 0.34:
        return "brown"
    return ("dark " if light < 0.3 else "light " if light > 0.72 else "") + name


def build_prompt(variant: str, description: str = "", purpose: "str | None" = None, *, text: bool = False, logo: bool = False,
                 sources: tuple = ("photo",), colour: str = "", scene: str = "") -> str:
    """The text sent with the photo. Without a description the model picks a neutral setting. The model never writes the texts
    itself: it only leaves room where the template puts them (`text`) and where the logo goes (`logo`)."""
    _size, shape, placement = VARIANTS[variant]
    description = " ".join(str(description or "").split())[:500]
    setting = (f"The object is: {description}. Choose the surroundings or background that suit this object and how it is used. "
               if description and variant != "studio" else "")
    # the owner's own words about where the object is shown; they come on top of the description, and a studio picture has no setting
    scene = " ".join(str(scene or "").split())[:SCENE_MAX]
    if scene and variant != "studio":
        setting += f"Show it in this setting: {scene}. "
    # a colour chosen for the item wins over the colour it has in the pictures given
    tint = (f"Show the object 3D printed in {colour_name(colour)} filament (colour {colour}), whatever colour it has in the picture given; "
            "its shape and everything else about it stay the same. " if COLOUR.match(colour or "") else "")
    return PROMPT.format(lead=lead(tuple(sources), shape), placement=placement, setting=setting + tint,
                         purpose=PURPOSES[purpose][1] if purpose else "",
                         room=(image_overlay.room(variant) if text else "") + (ROOM_FOR_LOGO if logo else ""))


# --- what the pictures are for, and the texts on them ---------------------------------------------------------------

def _line(value) -> str:
    return " ".join(str(value or "").split())


def image_text(value) -> dict:
    """The purpose and the texts of a calculation's pictures, checked: {purpose, colour, scene, product_name, specs, extra_text, logo}.
    `scene` is the owner's own description of the setting the object is shown in; it is added to the prompt. The
    colour is the item's own (`#rrggbb`), or empty to leave it as it is in the photo. The
    specifications are a list of short lines (a text is split on its lines, and a typed bullet is dropped)."""
    if value in (None, ""):
        value = {}
    if not isinstance(value, dict):
        raise ApiError(400, "ai.err_text")
    purpose = value.get("purpose") or None
    if purpose is not None and (not isinstance(purpose, str) or purpose not in PURPOSES):
        raise ApiError(400, "ai.err_purpose")
    specs = value.get("specs") or []
    if isinstance(specs, str):
        specs = specs.splitlines()
    if not isinstance(specs, list) or any(not isinstance(s, str) for s in specs):
        raise ApiError(400, "ai.err_text")
    specs = [text("ai.f_spec", required=False, max_len=SPEC_MAX)(_line(s).lstrip("-*•·").strip()) for s in specs]
    specs = [s for s in specs if s]
    if len(specs) > SPECS_MAX:
        raise ApiError(400, "ai.err_specs_many", max=SPECS_MAX)
    colour = str(value.get("colour") or "").strip().lower()
    if colour and not COLOUR.match(colour):
        raise ApiError(400, "ai.err_colour")
    return {"purpose": purpose, "colour": colour,
            "scene": text("ai.f_scene", required=False, max_len=SCENE_MAX)(_line(value.get("scene"))),
            "product_name": text("ai.f_product_name", required=False, max_len=NAME_MAX)(_line(value.get("product_name"))),
            "specs": specs,
            "extra_text": text("ai.f_extra_text", required=False, max_len=EXTRA_MAX)(_line(value.get("extra_text"))),
            "logo": value.get("logo") is True}


def text_complete(settings: dict) -> bool:
    """The texts go on the poster only when all of them are there; with one missing the pictures are made without any."""
    return bool(settings["product_name"] and settings["specs"] and settings["extra_text"])


def _stored_text(project) -> dict:
    try:
        return image_text(project["image_text"])
    except ApiError:                                               # something an older release left: start empty rather than fail
        return image_text({})


def _save_text(conn, project_id, settings: dict) -> None:
    conn.execute("UPDATE projects SET image_text = %s WHERE id = %s", (json.dumps(settings), project_id))


@bp.put("/projects/<uuid:project_id>/images/settings")
def put_image_text(project_id):
    """Keep the purpose and the texts with the calculation (it is not part of the calculation's own save)."""
    settings = image_text(json_body())
    with pool().connection() as conn:
        _project(conn, project_id)
        _save_text(conn, project_id, settings)
    return jsonify(settings)


# --- settings ----------------------------------------------------------------------------------------------------

SETTINGS = "api_key_enc, model, quality, price_text_in, price_image_in, price_image_out, usd_eur"


def _settings(conn) -> dict:
    row = conn.execute(f"SELECT {SETTINGS} FROM ai_image_settings").fetchone()
    return row or {"api_key_enc": None, "model": DEFAULT_MODEL, "quality": "medium", "price_text_in": None, "price_image_in": None, "price_image_out": None, "usd_eur": None}


def _plain(value) -> "str | None":
    """A number as people write it (`5`, `0.92`, not `5.0000`); None stays None."""
    return None if value is None else format(value.normalize(), "f")


def _read_key(row) -> "str | None":
    if not row["api_key_enc"]:
        return None
    raw = passwords.unseal(config().session_secret, row["api_key_enc"].encode(), KEY_INFO)
    return raw.decode() if raw is not None else None


def _public(row) -> dict:
    """What the browser may see: whether there is a key and its tail, never the key."""
    key = _read_key(row)
    return {"configured": bool(row["api_key_enc"]), "readable": key is not None or not row["api_key_enc"],
            "last4": key[-4:] if key else "", "model": row["model"], "quality": row["quality"],
            # what was typed (None: nothing), OpenAI's list price for this model where it is known, and the rate
            "prices": {k: _plain(row[f"price_{k}"]) for k in PRICE_KEYS}, "price_defaults": {k: _plain(v) for k, v in DEFAULT_PRICES.get(row["model"], {}).items()},
            "usd_eur": _plain(row["usd_eur"])}


def _number(value, label: str, *, maximum: Decimal, positive: bool = False) -> "Decimal | None":
    """A price or a rate as typed (`0,92` is as good as `0.92`); empty is None, which takes the typed value away. Anything else that is not a finite number in range is refused."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    key = "ai.err_rate" if positive else "ai.err_price"
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ApiError(400, key, max=_plain(maximum))
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise ApiError(400, key, max=_plain(maximum)) from None
    if not number.is_finite() or number < 0 or number > maximum or (positive and number == 0):
        raise ApiError(400, key, max=_plain(maximum))
    return number.quantize(Decimal("0.0001"), ROUND_HALF_UP)


def _typed_prices(prices, rate, row) -> dict:
    """The three prices and the rate after this request: what the request names (a key that is left out stays), else what was there."""
    if prices is not None and not isinstance(prices, dict):
        raise ApiError(400, "ai.err_price", max=_plain(MAX_PRICE))
    out = {k: row[f"price_{k}"] for k in PRICE_KEYS}
    out["usd_eur"] = row["usd_eur"]
    for k in PRICE_KEYS:
        if prices and k in prices:
            out[k] = _number(prices[k], k, maximum=MAX_PRICE)
    if rate is not ...:
        out["usd_eur"] = _number(rate, "usd_eur", maximum=MAX_RATE, positive=True)
    return out


@bp.get("/ai-images/settings")
def get_settings():
    with pool().read() as conn:
        return jsonify(_public(_settings(conn)))


@bp.put("/ai-images/settings")
def put_settings():
    body = json_body()
    with pool().connection() as conn:
        row = _settings(conn)
        model = row["model"]
        if "model" in body:
            model = text("ai.model", max_len=60)(body["model"])
            if not MODEL.match(model):
                raise ApiError(400, "ai.err_model_name")
        quality = body.get("quality", row["quality"])
        if quality not in QUALITIES:
            raise ApiError(400, "ai.err_quality")
        enc = row["api_key_enc"]
        if body.get("api_key") not in (None, ""):
            key = str(body["api_key"]).strip()
            if not KEY.match(key):
                raise ApiError(400, "ai.err_key_format")
            enc = passwords.seal(config().session_secret, key.encode(), KEY_INFO).decode()
        typed = _typed_prices(body.get("prices"), body.get("usd_eur", ...), row)
        if model != row["model"]:                           # the prices typed belonged to the model that was: for this one they are not known until they are typed
            for k in PRICE_KEYS:
                if not (isinstance(body.get("prices"), dict) and k in body["prices"]):
                    typed[k] = None
        saved = conn.execute(
            "INSERT INTO ai_image_settings (id, api_key_enc, model, quality, price_text_in, price_image_in, price_image_out, usd_eur) VALUES (true, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET api_key_enc = EXCLUDED.api_key_enc, model = EXCLUDED.model, quality = EXCLUDED.quality, price_text_in = EXCLUDED.price_text_in, "
            "price_image_in = EXCLUDED.price_image_in, price_image_out = EXCLUDED.price_image_out, usd_eur = EXCLUDED.usd_eur, updated_at = now() "
            f"RETURNING {SETTINGS}", (enc, model, quality, typed["text_in"], typed["image_in"], typed["image_out"], typed["usd_eur"])).fetchone()
        if enc != row["api_key_enc"]:
            _log(conn, "info", "ai.log_key_saved")
        if (model, quality) != (row["model"], row["quality"]):
            _log(conn, "info", "ai.log_settings", model=model, quality=quality)
        if any(typed[k] != row[f"price_{k}" if k != "usd_eur" else k] for k in (*PRICE_KEYS, "usd_eur")):
            _log(conn, "info", "ai.log_prices")
    return jsonify(_public(saved))


@bp.delete("/ai-images/key")
def delete_key():
    with pool().connection() as conn:
        had = conn.execute("UPDATE ai_image_settings SET api_key_enc = NULL, updated_at = now() WHERE api_key_enc IS NOT NULL RETURNING 1").fetchone()
        if had:
            _log(conn, "info", "ai.log_key_removed")
        return jsonify(_public(_settings(conn)))


def _need_key() -> "tuple[str, str, str]":
    """(key, model, quality) for a call; the connection is released before the slow request starts."""
    with pool().read() as conn:
        row = _settings(conn)
    if not row["api_key_enc"]:
        raise ApiError(400, "ai.err_no_key")
    key = _read_key(row)
    if key is None:
        raise ApiError(400, "ai.err_key_unreadable")
    return key, row["model"], row["quality"]


# --- the log -------------------------------------------------------------------------------------------------------

def _scrub(value, key: str = "") -> str:
    """Text from OpenAI for the log: it is cut short and anything that looks like (a piece of) an API key is taken out."""
    value = str(value or "")
    if key:
        value = value.replace(key, "…")
    return SECRET_LIKE.sub("sk-…", value)[:300]


def _freeze(params: dict) -> str:
    """Message parameters as JSON; a parameter that is itself a message (a field name) is kept as one, to be worded when it is read."""
    def plain(value):
        if isinstance(value, L):
            return {"_l": value.key, "p": {k: plain(v) for k, v in value.params.items()}}
        return value
    return json.dumps({k: plain(v) for k, v in params.items()}, default=str)


def _message(key: str, params: dict) -> L:
    def thaw(value):
        return L(value["_l"], **{k: thaw(v) for k, v in value["p"].items()}) if isinstance(value, dict) and "_l" in value else value
    return L(key, **{k: thaw(v) for k, v in params.items()})


def _log(conn, level: str, key: str, *, project=None, variant=None, detail: str = "", **params) -> None:
    """One line in the log: a message key with its parameters (worded in the language of whoever reads it), and for an error what OpenAI said."""
    conn.execute(
        "INSERT INTO ai_image_log (level, message_key, message_params, detail, project_id, project_number, project_name, variant) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (level, key, _freeze(params), detail[:300], project["id"] if project else None,
         project["number"] if project else None, project["name"] if project else None, variant))
    conn.execute("DELETE FROM ai_image_log WHERE id <= (SELECT id FROM ai_image_log ORDER BY id DESC LIMIT 1 OFFSET %s)", (LOG_KEEP,))


def _log_error(exc: ApiError, *, project=None, variant=None) -> None:
    """An error becomes a line of its own, in its own transaction (the one it came out of may have been rolled back)."""
    with pool().connection() as conn:
        _log(conn, "error", exc.msg.key, project=project, variant=variant, detail=getattr(exc, "detail", ""), **exc.msg.params)


def _project_of(project_id):
    with pool().read() as conn:
        return conn.execute("SELECT id, number, name FROM projects WHERE id = %s", (project_id,)).fetchone()


# --- talking to OpenAI -------------------------------------------------------------------------------------------

class AiError(ApiError):
    """A refusal from OpenAI: the message for the owner, plus what OpenAI itself said (kept in the log, never repeated to the screen)."""

    def __init__(self, status: int, message, *, detail: str = "", **params):
        super().__init__(status, message, **params)
        self.detail = detail


def _fail(response, key: str = "") -> AiError:
    """A refusal from OpenAI as an error the owner can act on. The key and the request are never repeated."""
    try:
        error = (response.json() or {}).get("error") or {}
    except ValueError:
        error = {}
    code, reason = str(error.get("code") or ""), _scrub(error.get("message"), key)
    detail = f"HTTP {response.status_code}" + (f" {code}" if code else "") + (f": {reason}" if reason else "")
    if response.status_code == 401:
        return AiError(400, "ai.err_key_invalid", detail=detail)
    if response.status_code == 429:
        return AiError(429, "ai.err_quota" if code == "insufficient_quota" else "ai.err_busy", detail=detail)
    if code in ("moderation_blocked", "content_policy_violation"):
        return AiError(422, "ai.err_policy", detail=detail)
    if response.status_code == 404:
        return AiError(400, "ai.err_model_unknown", detail=detail)
    if response.status_code >= 500:
        return AiError(502, "ai.err_upstream", detail=detail)
    return AiError(400, "ai.err_rejected", detail=detail, reason=reason[:200] or str(response.status_code))


def _call(method: str, url: str, key: str, **kwargs):
    try:
        response = requests.request(method, url, headers={"Authorization": f"Bearer {key}"}, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), **kwargs)
    except requests.Timeout:
        raise AiError(504, "ai.err_timeout", detail="timeout") from None
    except requests.RequestException as exc:
        raise AiError(502, "ai.err_unreachable", detail=type(exc).__name__) from None
    if response.status_code >= 400:
        raise _fail(response, key)
    return response


@bp.post("/ai-images/test")
def test_connection():
    try:
        key, model, _quality = _need_key()
        _call("GET", f"{OPENAI}/models/{model}", key)
    except ApiError as exc:
        _log_error(exc)
        raise
    with pool().connection() as conn:
        _log(conn, "info", "ai.log_test_ok", model=model)
    return jsonify({"ok": True})


# --- pictures ----------------------------------------------------------------------------------------------------

def _clean(content: bytes, *, jpeg_quality: int = 92, max_edge: int = MAX_EDGE) -> "tuple[bytes, int, int]":
    """Decode an image, apply its rotation, scale it down, and write it again as JPEG: nothing of the original file (metadata, a
    second payload after the image data) is kept. Raises ApiError for what is not a usable photo."""
    if len(content) > MAX_PHOTO_BYTES * 2:
        raise ApiError(400, "ai.err_photo_big")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in PHOTO_FORMATS:
                raise ApiError(400, "ai.err_photo_kind")
            if image.width < 1 or image.height < 1 or image.width * image.height > MAX_PIXELS:
                raise ApiError(400, "ai.err_photo_big")
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                image = flat
            else:
                image = image.convert("RGB")
            image.thumbnail((max_edge, max_edge))
            out = BytesIO()
            image.save(out, "JPEG", quality=jpeg_quality, optimize=True)
            return out.getvalue(), image.width, image.height
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ApiError(400, "ai.err_photo_kind") from None


def _serialise(row) -> dict:
    return {"id": str(row["id"]), "kind": row["kind"], "origin": row["origin"] if row["kind"] == "source" else None,
            "selected": bool(row["selected"]) if row["kind"] == "source" else None,
            "model_ref": row["model_ref"] if row["kind"] == "source" else None,
            "variant": row["variant"], "purpose": row["purpose"], "width_px": row["width_px"],
            "height_px": row["height_px"], "is_cover": row["is_cover"], "created_at": row["created_at"].isoformat()}


def _project(conn, project_id):
    row = conn.execute("SELECT id, number, name, object_description, image_text FROM projects WHERE id = %s", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.calc_not_found")
    return row


COLUMNS = "id, kind, origin, model_ref, selected, variant, purpose, width_px, height_px, is_cover, created_at"


def _job_json(row) -> dict:
    message = render(_message(row["error_key"], row["error_params"]), request_language()) if row["error_key"] else None
    return {"id": str(row["id"]), "variant": row["variant"], "purpose": row["purpose"], "status": row["status"], "message": message,
            "detail": row["detail"]}


def _warnings(jobs) -> list:
    """What the pictures of this batch are made without, although it was asked for, worded for whoever reads it. They are decided
    when the batch is queued and kept on its jobs, so the page shows them while the pictures are made and afterwards."""
    keys = []
    for job in jobs:
        for key in (job["overlay"] or {}).get("warnings") or []:
            if key in WARNINGS and key not in keys:
                keys.append(key)
    return [render(L(key), request_language()) for key in keys]


def _recover(conn) -> None:
    """Give up on jobs that have not moved for a while: their thread died with its container, and nobody would ever finish them."""
    rows = conn.execute(
        "UPDATE ai_image_jobs SET status = 'failed', error_key = 'ai.err_interrupted', finished_at = now(), updated_at = now() "
        "WHERE status IN ('queued', 'running') AND updated_at < %s RETURNING project_id, variant",
        (datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES),)).fetchall()
    for row in rows:
        project = conn.execute("SELECT id, number, name FROM projects WHERE id = %s", (row["project_id"],)).fetchone()
        _log(conn, "error", "ai.err_interrupted", project=project, variant=row["variant"])


@bp.get("/projects/<uuid:project_id>/images")
def list_images(project_id):
    with pool().connection() as conn:
        project = _project(conn, project_id)
        _recover(conn)
        has_logo = conn.execute("SELECT 1 FROM invoice_logo").fetchone() is not None
        sent = _sent(conn, project_id, "id")
        rows = conn.execute(f"SELECT {COLUMNS} FROM project_images WHERE project_id = %s ORDER BY kind DESC, origin DESC, created_at, id",
                            (project_id,)).fetchall()
        jobs = conn.execute("SELECT * FROM ai_image_jobs WHERE project_id = %s ORDER BY created_at, position",
                            (project_id,)).fetchall()
    return jsonify({"images": [_serialise(r) for r in rows], "jobs": [_job_json(j) for j in jobs], "warnings": _warnings(jobs),
                    "text": _stored_text(project),
                    "logo_available": has_logo, "purposes": {name: list(made) for name, (made, _style) in PURPOSES.items()},
                    "sent": [str(r["id"]) for r in sent],
                    "limits": {"selected": MAX_SELECTED, "product_name": NAME_MAX, "spec": SPEC_MAX, "specs": SPECS_MAX, "extra_text": EXTRA_MAX, "scene": SCENE_MAX}})


@bp.delete("/projects/<uuid:project_id>/images/jobs")
def dismiss_jobs(project_id):
    """Hide the failed pictures' messages (the log keeps them)."""
    with pool().connection() as conn:
        _project(conn, project_id)
        conn.execute("DELETE FROM ai_image_jobs WHERE project_id = %s AND status IN ('failed', 'done')", (project_id,))
    return jsonify({"ok": True})


@bp.post("/projects/<uuid:project_id>/images/source")
def upload_source(project_id):
    """Keep the picture the images are made from: a photo of the object, or (`origin=model`) a picture of its 3D model as the viewer
    in the browser drew it. Every one is kept, next to the others: up to MAX_PHOTOS photos and MAX_MODEL_VIEWS views (`model` says
    which model and build plate a view shows: "<file id>" or "<file id>:<plate>"). The first picture of a calculation is the one
    that goes to the image model; which others go with it is chosen afterwards (`PUT /project-images/<id>/selected`)."""
    upload = request.files.get("file")
    origin = request.form.get("origin", "photo")
    model_ref = request.form.get("model", "").strip().lower() if origin == "model" else ""
    try:
        if origin not in ORIGINS or (model_ref and not MODEL_REF.match(model_ref)):
            raise ApiError(400, "ai.err_origin")
        if upload is None or not upload.filename:
            raise ApiError(400, "ai.err_photo_pick")
        content, width, height = _clean(upload.stream.read(MAX_PHOTO_BYTES * 2 + 1))
    except ApiError as exc:
        _log_error(exc, project=_project_of(project_id))
        raise
    with pool().connection() as conn:
        project = _project(conn, project_id)
        there = {r["origin"]: r["n"] for r in conn.execute(
            "SELECT origin, count(*) AS n FROM project_images WHERE project_id = %s AND kind = 'source' GROUP BY origin", (project_id,)).fetchall()}
        if origin == "model" and there.get("model", 0) >= MAX_MODEL_VIEWS:
            raise ApiError(409, "ai.err_views_many", max=MAX_MODEL_VIEWS)
        if origin == "photo" and there.get("photo", 0) >= MAX_PHOTOS:
            raise ApiError(409, "ai.err_photos_many", max=MAX_PHOTOS)
        row = conn.execute(
            f"INSERT INTO project_images (project_id, kind, origin, model_ref, selected, mime, content, width_px, height_px) "
            f"VALUES (%s, 'source', %s, %s, %s, 'image/jpeg', %s, %s, %s) RETURNING {COLUMNS}",
            (project_id, origin, model_ref, not there, content, width, height)).fetchone()        # the first picture is the one that is sent
        _log(conn, "info", "ai.log_photo" if origin == "photo" else "ai.log_model_view", project=project)
    return jsonify(_serialise(row)), 201


def _enqueue(project_id, body: dict) -> "tuple[uuid.UUID, list]":
    typed = image_text(body["text"]) if "text" in body else None   # what the form holds now; it is saved with the request
    _need_key()                                                    # no key: say so now, not after the queue has been made
    batch = uuid.uuid4()
    with pool().connection() as conn:
        project = _project(conn, project_id)            # two requests at once for one calculation: one waits for the other (the write lock)
        settings = typed or _stored_text(project)
        if "purpose" in body:
            settings = image_text({**settings, "purpose": body["purpose"]})
        purpose = settings["purpose"]
        if purpose is None:
            raise ApiError(400, "ai.err_purpose")
        variants = body.get("variants", list(PURPOSES[purpose][0]))
        if (not isinstance(variants, list) or not variants or len(set(map(str, variants))) != len(variants)
                or any(v not in PURPOSES[purpose][0] for v in variants)):
            raise ApiError(400, "ai.err_variant")
        # the logo is the business's: it only goes on while the person asking has the business mode on, whatever the switch says
        business = bool(preferences.load(conn, g.user_id).get("business_mode"))
        has_logo = conn.execute("SELECT 1 FROM invoice_logo").fetchone() is not None
        logo = settings["logo"] and business
        poster = {k: settings[k] for k in ("product_name", "specs", "extra_text")} if text_complete(settings) else None
        warnings = []
        if poster is None and (settings["product_name"] or settings["specs"] or settings["extra_text"]):
            warnings.append("ai.warn_text_incomplete")             # some texts were typed, and none of them will be on a picture
        if settings["logo"] and not business:
            warnings.append("ai.warn_logo_business")
        elif logo and not has_logo:
            warnings.append("ai.warn_logo_none")
        _recover(conn)
        if conn.execute("SELECT 1 FROM ai_image_jobs WHERE project_id = %s AND status IN ('queued', 'running')", (project_id,)).fetchone():
            raise ApiError(409, "ai.err_already_busy")
        if conn.execute("SELECT 1 FROM project_images WHERE project_id = %s AND kind = 'source'", (project_id,)).fetchone() is None:
            raise ApiError(400, "ai.err_no_photo")
        made = conn.execute("SELECT count(*) AS n FROM project_images WHERE project_id = %s AND kind = 'generated'", (project_id,)).fetchone()["n"]
        if made + len(variants) > MAX_GENERATED:
            raise ApiError(409, "ai.err_too_many", max=MAX_GENERATED)
        description = body["description"] if "description" in body else project["object_description"]   # the form may hold text not yet saved
        description = text("f.object_description", required=False, max_len=500)(description)
        for _ in variants:
            _limit.check("generate")
        _save_text(conn, project_id, settings)
        conn.execute("DELETE FROM ai_image_jobs WHERE project_id = %s", (project_id,))                  # the finished ones of the last time
        for position, variant in enumerate(variants):
            conn.execute("INSERT INTO ai_image_jobs (project_id, batch_id, position, variant, description, purpose, overlay) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                         (project_id, batch, position, variant, description, purpose,
                          json.dumps({"text": poster if variant == PURPOSES[purpose][0][0] else None, "logo": logo, "warnings": warnings,
                                      "colour": settings["colour"], "scene": settings["scene"]})))
        _log(conn, "info", "ai.log_queued", project=project, n=len(variants))
        for key in warnings:
            _log(conn, "info", key, project=project)
        jobs = conn.execute("SELECT * FROM ai_image_jobs WHERE batch_id = %s ORDER BY position", (batch,)).fetchall()
    return batch, jobs


@bp.post("/projects/<uuid:project_id>/images/generate")
def generate(project_id):
    """Queue the pictures and answer at once; they are made in the background and polled with GET .../images."""
    body = json_body()
    try:
        batch, jobs = _enqueue(project_id, body)
    except ApiError as exc:
        _log_error(exc, project=_project_of(project_id))
        raise
    _start(current_app._get_current_object(), project_id, batch)
    return jsonify({"jobs": [_job_json(j) for j in jobs], "warnings": _warnings(jobs)}), 202


# --- the background thread ---------------------------------------------------------------------------------------------

def _start(app, project_id, batch):
    """Make the queued pictures of this batch in a thread (tests replace this to run them on the spot)."""
    thread = threading.Thread(target=_run_batch, args=(app, project_id, batch), name="ai-images", daemon=True)
    thread.start()
    return thread


def _run_batch(app, project_id, batch) -> None:
    with app.app_context():
        try:
            while _run_next(project_id, batch):
                pass
        except Exception:
            log.exception("AI image batch %s failed", batch)
            try:
                _give_up(project_id, batch, ApiError(500, "ai.err_unexpected"), None)
            except Exception:
                log.exception("could not mark AI image batch %s as failed", batch)


def _generate(key: str, model: str, quality: str, variant: str, description: str, sources: list, purpose=None, *, text=False, logo=False,
              colour="", scene=""):
    """`sources` is [(origin, jpeg), ...], the photo first, then the views of the models. One picture is sent as `image`, more as
    `image[]`."""
    prompt = build_prompt(variant, description, purpose, text=text, logo=logo, sources=tuple(origin for origin, _ in sources), colour=colour,
                          scene=scene)
    # returns (jpeg, width, height, the tokens OpenAI counted or None: see `usage_of`)
    if len(sources) == 1:
        files = {"image": (f"{sources[0][0]}.jpg", sources[0][1], "image/jpeg")}
    else:
        files, seen = [], {}
        for origin, content in sources:                                  # photo.jpg, photo-2.jpg, model.jpg, model-2.jpg ...
            seen[origin] = seen.get(origin, 0) + 1
            files.append(("image[]", (f"{origin}.jpg" if seen[origin] == 1 else f"{origin}-{seen[origin]}.jpg", content, "image/jpeg")))
    response = _call("POST", f"{OPENAI}/images/edits", key,
                     data={"model": model, "prompt": prompt, "size": VARIANTS[variant][0], "quality": quality, "n": "1"},
                     files=files)
    try:
        answer = response.json()
        content, width, height = _clean(base64.b64decode(answer["data"][0]["b64_json"], validate=True))
    except (ApiError, ValueError, KeyError, IndexError, TypeError):
        raise AiError(502, "ai.err_bad_result", detail="no usable image in the answer") from None
    return content, width, height, usage_of(answer)


def _give_up(project_id, batch, exc: ApiError, project) -> None:
    """Fail every picture of the batch that has not been made."""
    with pool().connection() as conn:
        rows = conn.execute(
            "UPDATE ai_image_jobs SET status = 'failed', error_key = %s, error_params = %s, detail = %s, finished_at = now(), updated_at = now() "
            "WHERE batch_id = %s AND status IN ('queued', 'running') RETURNING variant",
            (exc.msg.key, _freeze(exc.msg.params), getattr(exc, "detail", "")[:300], batch)).fetchall()
        for row in rows:
            _log(conn, "error", exc.msg.key, project=project, variant=row["variant"], detail=getattr(exc, "detail", ""), **exc.msg.params)


def _run_next(project_id, batch) -> bool:
    """Make the next queued picture of the batch. False when there is nothing (more) to do."""
    with pool().connection() as conn:
        job = conn.execute(
            "UPDATE ai_image_jobs SET status = 'running', updated_at = now() WHERE id = (SELECT id FROM ai_image_jobs "
            "WHERE batch_id = %s AND status = 'queued' ORDER BY position LIMIT 1) RETURNING *", (batch,)).fetchone()
        if job is None:
            return False
        conn.execute("UPDATE ai_image_jobs SET updated_at = now() WHERE batch_id = %s AND status = 'queued'", (batch,))     # still alive
        project = conn.execute("SELECT id, number, name FROM projects WHERE id = %s", (project_id,)).fetchone()
        sources = [(r["origin"], bytes(r["content"])) for r in _sent(conn, project_id, "origin, content")]
        overlay = job["overlay"] or {}
        logo = invoice_logo.load(conn) if overlay.get("logo") else None        # no logo uploaded: the picture is made without one
        if project is not None:
            _log(conn, "info", "ai.log_started", project=project, variant=job["variant"])
    if project is None:
        return False                                              # the calculation was deleted: its jobs went with it
    started = time.monotonic()
    try:
        key, model, quality = _need_key()
        if not sources:
            raise ApiError(400, "ai.err_no_photo")
        content, width, height, usage = _generate(key, model, quality, job["variant"], job["description"], sources, job["purpose"],
                                                  text=bool(overlay.get("text")), logo=logo is not None, colour=overlay.get("colour") or "",
                                                  scene=overlay.get("scene") or "")
        if job["purpose"] and (overlay.get("text") or logo):
            content = image_overlay.compose(content, job["purpose"], job["variant"], text=overlay.get("text"), logo=logo["content"] if logo else None)
    except ApiError as exc:
        return _failed(project_id, batch, job, project, exc)
    except Exception:
        log.exception("AI image job %s failed", job["id"])
        return _failed(project_id, batch, job, project, AiError(500, "ai.err_unexpected", detail="see the server log"))
    try:
        with pool().connection() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,)).fetchone() is None:
                return False
            conn.execute("INSERT INTO project_images (project_id, kind, variant, purpose, mime, content, width_px, height_px) "
                         "VALUES (%s, 'generated', %s, %s, 'image/jpeg', %s, %s, %s)",
                         (project_id, job["variant"], job["purpose"], content, width, height))
            conn.execute("UPDATE ai_image_jobs SET status = 'done', finished_at = now(), updated_at = now() WHERE id = %s", (job["id"],))
            _record_usage(conn, job, project, model, quality, usage)          # with the picture: no picture without what it cost, no cost without a picture
            _log(conn, "info", "ai.log_done", project=project, variant=job["variant"], seconds=round(time.monotonic() - started))
    except ForeignKeyViolation:
        return False
    return True


def _failed(project_id, batch, job, project, exc: ApiError) -> bool:
    """One picture failed. Whether the others still have a chance depends on why."""
    detail = getattr(exc, "detail", "")
    with pool().connection() as conn:
        conn.execute("UPDATE ai_image_jobs SET status = 'failed', error_key = %s, error_params = %s, detail = %s, finished_at = now(), updated_at = now() "
                     "WHERE id = %s", (exc.msg.key, _freeze(exc.msg.params), detail[:300], job["id"]))
        _log(conn, "error", exc.msg.key, project=project, variant=job["variant"], detail=detail, **exc.msg.params)
    if exc.msg.key in ABORT_KEYS:
        _give_up(project_id, batch, exc, project)
        return False
    return True


# --- what the pictures cost ----------------------------------------------------------------------------------------------

def _count(value) -> "int | None":
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_TOKENS else None


def usage_of(answer) -> "dict | None":
    """The tokens OpenAI counted for one picture, from `usage` in its answer: the text and the image tokens that went in, and the tokens that came out. None when the answer
    does not say it completely (the fields are whole numbers or they are nothing): a cost is never guessed from half an answer."""
    usage = answer.get("usage") if isinstance(answer, dict) else None
    details = usage.get("input_tokens_details") if isinstance(usage, dict) else None
    if not isinstance(details, dict):
        return None
    counted = {"input_text": _count(details.get("text_tokens")), "input_image": _count(details.get("image_tokens")), "output": _count(usage.get("output_tokens"))}
    return None if None in counted.values() else counted


def prices_for(settings, model: str) -> dict:
    """What a million tokens of each kind cost in dollars for `model`: what was typed (only if it was typed for this model), else OpenAI's list price for it, else None."""
    default = DEFAULT_PRICES.get(model, {})
    own = settings["model"] == model
    return {k: settings[f"price_{k}"] if own and settings[f"price_{k}"] is not None else default.get(k) for k in PRICE_KEYS}


def _record_usage(conn, job, project, model: str, quality: str, usage) -> None:
    """One row for the picture that was just made, with the prices and the rate as they are now."""
    settings = _settings(conn)
    price = prices_for(settings, model)
    counted = usage or {"input_text": 0, "input_image": 0, "output": 0}
    conn.execute(
        "INSERT INTO ai_image_usage (batch_id, project_id, project_number, project_name, purpose, variant, model, quality, reported, input_text_tokens, input_image_tokens, "
        "output_tokens, price_text_in, price_image_in, price_image_out, usd_eur) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (job["batch_id"], project["id"], project["number"], project["name"], job["purpose"], job["variant"], model, quality, usage is not None,
         counted["input_text"], counted["input_image"], counted["output"], price["text_in"], price["image_in"], price["image_out"], settings["usd_eur"]))


def cost_usd(row) -> "Decimal | None":
    """What one picture cost in dollars, exact: tokens times the price of its kind per million. None when OpenAI did not say how many tokens, or a kind that was used had no price then."""
    if not row["reported"]:
        return None
    total = Decimal(0)
    for tokens, price in ((row["input_text_tokens"], row["price_text_in"]), (row["input_image_tokens"], row["price_image_in"]), (row["output_tokens"], row["price_image_out"])):
        if tokens:
            if price is None:
                return None
            total += Decimal(tokens) * price / MILLION
    return total


def sets_of(rows, rate) -> list:
    """The rows (newest first) as sets, one per request for pictures: when, which calculation, how many pictures, the tokens, and the cost in dollars and in euros. A set is rounded to
    cents (`CENT`) before sets are added to a total, so what is on the screen adds up. The euros of a picture use the rate it was made at, else `rate` (the current one); with no rate, or a
    picture whose cost is not known, the set has no euros (or dollars). `rate` is euros per dollar."""
    sets: dict = {}
    for row in rows:
        s = sets.setdefault(str(row["batch_id"]), {"batch_id": str(row["batch_id"]), "at": row["created_at"], "project_id": str(row["project_id"]) if row["project_id"] else None,
                                                    "project_number": row["project_number"], "project_name": row["project_name"], "purpose": row["purpose"], "pictures": 0,
                                                    "reported": True, "input_text": 0, "input_image": 0, "output": 0, "_usd": Decimal(0), "_eur": Decimal(0)})
        s["pictures"] += 1
        s["reported"] = s["reported"] and bool(row["reported"])
        s["input_text"] += row["input_text_tokens"]
        s["input_image"] += row["input_image_tokens"]
        s["output"] += row["output_tokens"]
        cost = cost_usd(row)
        at_rate = row["usd_eur"] if row["usd_eur"] is not None else rate
        s["_usd"] = None if cost is None or s["_usd"] is None else s["_usd"] + cost
        s["_eur"] = None if cost is None or at_rate is None or s["_eur"] is None else s["_eur"] + cost * at_rate
    for s in sets.values():
        usd, eur = s.pop("_usd"), s.pop("_eur")
        s["tokens"] = s["input_text"] + s["input_image"] + s["output"]
        s["cost_usd"] = None if usd is None else usd.quantize(CENT, ROUND_HALF_UP)
        s["cost_eur"] = None if eur is None else eur.quantize(CENT, ROUND_HALF_UP)
    return list(sets.values())


def _money(value) -> "str | None":
    return None if value is None else format(value, "f")


def _totals(sets) -> dict:
    """What the sets come to: how many, the tokens, and the cost in dollars and in euros of the sets that have one (the others are counted apart, so a total is never presented as more than it is)."""
    usd = [s["cost_usd"] for s in sets if s["cost_usd"] is not None]
    eur = [s["cost_eur"] for s in sets if s["cost_eur"] is not None]
    return {"sets": len(sets), "pictures": sum(s["pictures"] for s in sets), "tokens": sum(s["tokens"] for s in sets),
            "cost_usd": _money(sum(usd, Decimal(0))) if usd else None, "cost_eur": _money(sum(eur, Decimal(0))) if eur else None,
            "without_usd": len(sets) - len(usd), "without_eur": len(sets) - len(eur)}


def _set_json(s) -> dict:
    return {"batch_id": s["batch_id"], "at": s["at"].isoformat(), "project_id": s["project_id"], "project_number": s["project_number"], "project_name": s["project_name"],
            "purpose": s["purpose"], "pictures": s["pictures"], "reported": s["reported"],
            "tokens": {"input_text": s["input_text"], "input_image": s["input_image"], "output": s["output"], "total": s["tokens"]},
            "cost_usd": _money(s["cost_usd"]), "cost_eur": _money(s["cost_eur"])}


def usage_report(rows, settings, now) -> dict:
    """The answer of `GET /api/ai-images/usage`. `now` decides what "this month" is (UTC)."""
    rate = settings["usd_eur"]
    sets = sets_of(rows, rate)
    month = [s for s in sets if (s["at"].year, s["at"].month) == (now.year, now.month)]
    return {"sets": [_set_json(s) for s in sets[:MAX_SETS]], "totals": {"month": _totals(month), "all": _totals(sets)}, "model": settings["model"], "rate": _plain(rate),
            "prices": {k: _plain(v) for k, v in prices_for(settings, settings["model"]).items()}}


@bp.get("/ai-images/usage")
def get_usage():
    """What the pictures cost: the newest sets with their tokens and cost, and the totals of this month and of everything, and the prices and the rate they are worked out with."""
    with pool().read() as conn:
        settings = _settings(conn)
        rows = conn.execute("SELECT * FROM ai_image_usage ORDER BY created_at DESC, id DESC").fetchall()
    return jsonify(usage_report(rows, settings, datetime.now(timezone.utc)))


# --- the log -------------------------------------------------------------------------------------------------------------

@bp.get("/ai-images/log")
def get_log():
    with pool().read() as conn:
        rows = conn.execute("SELECT * FROM ai_image_log ORDER BY created_at DESC, id DESC LIMIT 200").fetchall()
    lang = request_language()
    return jsonify([{"id": r["id"], "created_at": r["created_at"].isoformat(), "level": r["level"],
                     "message": render(_message(r["message_key"], r["message_params"]), lang), "detail": r["detail"],
                     "project_id": str(r["project_id"]) if r["project_id"] else None, "project_number": r["project_number"],
                     "project_name": r["project_name"], "variant": r["variant"]} for r in rows])


@bp.delete("/ai-images/log")
def clear_log():
    with pool().connection() as conn:
        conn.execute("DELETE FROM ai_image_log")
        _log(conn, "info", "ai.log_cleared")
    return jsonify({"ok": True})


def _image_row(conn, image_id, columns=COLUMNS):
    row = conn.execute(f"SELECT {columns} FROM project_images WHERE id = %s", (image_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return row


def _kept(response, image_id):
    """A stored picture never changes: its bytes are written once (`project_images.content`; only `is_cover` is ever updated, which
    test_ai_images.py checks), so its id is its validator and the browser may keep it. The list of calculations shows a cover per
    row; without this every visit fetched every picture again."""
    response.set_etag(str(image_id))
    return keep_forever(response.make_conditional(request))


@bp.get("/project-images/<uuid:image_id>/file")
def image_file(image_id):
    with pool().read() as conn:
        row = _image_row(conn, image_id, "id, kind, variant, purpose, mime, content, project_id")
        number = conn.execute("SELECT number FROM projects WHERE id = %s", (row["project_id"],)).fetchone()["number"]
    if request.args.get("download") == "1":            # a download is named after the calculation, whose number is not part of the picture
        name = f"berekening-{number}-{'-'.join(filter(None, (row['purpose'], row['variant']))) or 'foto'}.jpg"
        return Response(bytes(row["content"]), mimetype=row["mime"], headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return _kept(Response(bytes(row["content"]), mimetype=row["mime"]), image_id)


@bp.get("/project-images/<uuid:image_id>/thumb")
def image_thumb(image_id):
    """The picture as the list shows it: at most THUMB_EDGE pixels a side instead of the stored one of up to 2048. It is made when asked
    for and not stored (a JPEG is decoded at a fraction of its size, which takes milliseconds), and kept by the browser like the picture
    itself, so each browser asks once per picture."""
    with pool().read() as conn:
        row = _image_row(conn, image_id, "id, content")
    with Image.open(BytesIO(bytes(row["content"]))) as image:
        image.draft("RGB", (THUMB_EDGE, THUMB_EDGE))
        image = image.convert("RGB")
        image.thumbnail((THUMB_EDGE, THUMB_EDGE))
        out = BytesIO()
        image.save(out, "JPEG", quality=80, optimize=True)
    return _kept(Response(out.getvalue(), mimetype="image/jpeg"), image_id)


def _sent(conn, project_id, columns: str) -> list:
    """The pictures that go to the image model for this calculation: the ones chosen for it, the photos first, at most MAX_SELECTED;
    when none is chosen (the chosen one was removed), the first picture there is."""
    order = "ORDER BY origin DESC, created_at, id"
    rows = conn.execute(f"SELECT {columns} FROM project_images WHERE project_id = %s AND kind = 'source' AND selected {order} LIMIT %s",
                        (project_id, MAX_SELECTED)).fetchall()
    return rows or conn.execute(f"SELECT {columns} FROM project_images WHERE project_id = %s AND kind = 'source' {order} LIMIT 1",
                                (project_id,)).fetchall()


@bp.put("/project-images/<uuid:image_id>/selected")
def set_selected(image_id):
    """Choose whether this photo or view goes to the image model. At most MAX_SELECTED of a calculation do."""
    wanted = json_body().get("selected")
    if not isinstance(wanted, bool):
        raise ApiError(400, "ai.err_selected")
    with pool().connection() as conn:
        row = _image_row(conn, image_id, COLUMNS + ", project_id")
        if row["kind"] != "source":
            raise ApiError(400, "ai.err_selected")
        chosen = conn.execute("SELECT count(*) AS n FROM project_images WHERE project_id = %s AND kind = 'source' AND selected AND id <> %s",
                              (row["project_id"], image_id)).fetchone()["n"]
        if wanted and chosen >= MAX_SELECTED:
            raise ApiError(409, "ai.err_selected_many", max=MAX_SELECTED)
        conn.execute("UPDATE project_images SET selected = %s WHERE id = %s", (wanted, image_id))
    return jsonify({**_serialise(row), "selected": wanted})


@bp.put("/project-images/<uuid:image_id>/cover")
def set_cover(image_id):
    with pool().connection() as conn:
        row = _image_row(conn, image_id)
        conn.execute("UPDATE project_images SET is_cover = false WHERE project_id = (SELECT project_id FROM project_images WHERE id = %s)",
                     (image_id,))
        conn.execute("UPDATE project_images SET is_cover = true WHERE id = %s", (image_id,))
    return jsonify({**_serialise(row), "is_cover": True})


@bp.delete("/project-images/<uuid:image_id>")
def delete_image(image_id):
    with pool().connection() as conn:
        _image_row(conn, image_id)
        conn.execute("DELETE FROM project_images WHERE id = %s", (image_id,))
    return jsonify({"ok": True})

