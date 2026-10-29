"""Optional AI product images: a photo of the printed object goes to OpenAI's image model, which puts it in a realistic setting.

Everything here exists only when `AI_IMAGES_ENABLED=TRUE` in .env: the flag is checked on the server for every route (404 when
off), the browser merely follows `ai_images` in /api/auth/status. The OpenAI key is typed under Settings and kept encrypted with a key
derived from SESSION_SECRET (`passwords.seal`); it is never sent back, only its last four characters. Photos and results are kept in the
database (`project_images`, like the invoice logo) and re-encoded on the way in, so nothing from an upload is stored as it came.

A picture takes a while, so asking for pictures only queues them (`ai_image_jobs`); a background thread of this web worker makes them one
by one and writes what happens to `ai_image_log`. The browser polls the jobs, so leaving the page stops nothing. A job whose thread died
(the container restarted) is marked failed once it has not moved for a few minutes."""
import base64
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import requests
from flask import Blueprint, Response, current_app, jsonify, request
from PIL import Image, ImageOps, UnidentifiedImageError

from . import passwords
from .api import text
from .db import ForeignKeyViolation
from .http import ApiError, RateLimiter, config, json_body, login_required, pool
from .i18n import L, render, request_language

log = logging.getLogger(__name__)

bp = Blueprint("ai_images", __name__, url_prefix="/api")

KEY_INFO = b"printpricing/ai-key/v1"
OPENAI = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2"
QUALITIES = ("low", "medium", "high")
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_EDGE = 2048                      # the photo is scaled down to this before it is stored and sent
MAX_GENERATED = 12                   # per calculation; delete some to make more
PHOTO_FORMATS = {"PNG", "JPEG", "MPO", "WEBP"}      # MPO is what some phones write as a JPEG
CONNECT_TIMEOUT, READ_TIMEOUT = 10, 100             # the whole request has to fit in gunicorn's 120 seconds
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
                 "Place the object naturally in a fitting everyday setting, the object in the lower two thirds."),
    "studio": ("1024x1024", "a square 1:1 studio picture",
               "Place the object on a plain, light, softly lit surface with a clean neutral background and a soft shadow."),
}
PROMPT = (
    "Edit this photo of a 3D-printed object into {shape}. Keep the object itself exactly as it is: same shape, proportions, colour "
    "and visible print layers; do not redesign, restyle or add parts to it. {placement} {setting}"
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


def build_prompt(variant: str, description: str = "") -> str:
    """The text sent with the photo. Without a description the model picks a neutral setting."""
    _size, shape, placement = VARIANTS[variant]
    description = " ".join(str(description or "").split())[:500]
    setting = (f"The object is: {description}. Choose the surroundings or background that suit this object and how it is used. "
               if description and variant != "studio" else "")
    return PROMPT.format(shape=shape, placement=placement, setting=setting)


# --- settings ----------------------------------------------------------------------------------------------------

def _settings(conn) -> dict:
    row = conn.execute("SELECT api_key_enc, model, quality FROM ai_image_settings").fetchone()
    return row or {"api_key_enc": None, "model": DEFAULT_MODEL, "quality": "medium"}


def _read_key(row) -> "str | None":
    if not row["api_key_enc"]:
        return None
    raw = passwords.unseal(config().session_secret, row["api_key_enc"].encode(), KEY_INFO)
    return raw.decode() if raw is not None else None


def _public(row) -> dict:
    """What the browser may see: whether there is a key and its tail, never the key."""
    key = _read_key(row)
    return {"configured": bool(row["api_key_enc"]), "readable": key is not None or not row["api_key_enc"],
            "last4": key[-4:] if key else "", "model": row["model"], "quality": row["quality"]}


@bp.get("/ai-images/settings")
def get_settings():
    with pool().connection() as conn:
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
        saved = conn.execute(
            "INSERT INTO ai_image_settings (id, api_key_enc, model, quality) VALUES (true, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET api_key_enc = EXCLUDED.api_key_enc, model = EXCLUDED.model, quality = EXCLUDED.quality, "
            "updated_at = now() RETURNING api_key_enc, model, quality", (enc, model, quality)).fetchone()
        if enc != row["api_key_enc"]:
            _log(conn, "info", "ai.log_key_saved")
        if (model, quality) != (row["model"], row["quality"]):
            _log(conn, "info", "ai.log_settings", model=model, quality=quality)
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
    with pool().connection() as conn:
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
    with pool().connection() as conn:
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

def _clean(content: bytes, *, jpeg_quality: int = 92) -> "tuple[bytes, int, int]":
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
            image.thumbnail((MAX_EDGE, MAX_EDGE))
            out = BytesIO()
            image.save(out, "JPEG", quality=jpeg_quality, optimize=True)
            return out.getvalue(), image.width, image.height
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ApiError(400, "ai.err_photo_kind") from None


def _serialise(row) -> dict:
    return {"id": str(row["id"]), "kind": row["kind"], "variant": row["variant"], "width_px": row["width_px"],
            "height_px": row["height_px"], "is_cover": row["is_cover"], "created_at": row["created_at"].isoformat()}


def _project(conn, project_id):
    row = conn.execute("SELECT id, number, name, object_description FROM projects WHERE id = %s", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.calc_not_found")
    return row


COLUMNS = "id, kind, variant, width_px, height_px, is_cover, created_at"


def _job_json(row) -> dict:
    message = render(_message(row["error_key"], row["error_params"]), request_language()) if row["error_key"] else None
    return {"id": str(row["id"]), "variant": row["variant"], "status": row["status"], "message": message, "detail": row["detail"]}


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
        _project(conn, project_id)
        _recover(conn)
        rows = conn.execute(f"SELECT {COLUMNS} FROM project_images WHERE project_id = %s ORDER BY kind DESC, created_at, id",
                            (project_id,)).fetchall()
        jobs = conn.execute("SELECT * FROM ai_image_jobs WHERE project_id = %s ORDER BY created_at, position",
                            (project_id,)).fetchall()
    return jsonify({"images": [_serialise(r) for r in rows], "jobs": [_job_json(j) for j in jobs]})


@bp.delete("/projects/<uuid:project_id>/images/jobs")
def dismiss_jobs(project_id):
    """Hide the failed pictures' messages (the log keeps them)."""
    with pool().connection() as conn:
        _project(conn, project_id)
        conn.execute("DELETE FROM ai_image_jobs WHERE project_id = %s AND status IN ('failed', 'done')", (project_id,))
    return jsonify({"ok": True})


@bp.post("/projects/<uuid:project_id>/images/source")
def upload_source(project_id):
    upload = request.files.get("file")
    try:
        if upload is None or not upload.filename:
            raise ApiError(400, "ai.err_photo_pick")
        content, width, height = _clean(upload.stream.read(MAX_PHOTO_BYTES * 2 + 1))
    except ApiError as exc:
        _log_error(exc, project=_project_of(project_id))
        raise
    with pool().connection() as conn:
        project = _project(conn, project_id)
        conn.execute("DELETE FROM project_images WHERE project_id = %s AND kind = 'source'", (project_id,))
        row = conn.execute(
            f"INSERT INTO project_images (project_id, kind, mime, content, width_px, height_px) VALUES (%s, 'source', 'image/jpeg', %s, %s, %s) "
            f"RETURNING {COLUMNS}", (project_id, content, width, height)).fetchone()
        _log(conn, "info", "ai.log_photo", project=project)
    return jsonify(_serialise(row)), 201


def _enqueue(project_id, body: dict) -> "tuple[uuid.UUID, list]":
    variants = body.get("variants", list(VARIANTS))
    if not isinstance(variants, list) or not variants or len(set(map(str, variants))) != len(variants) or any(v not in VARIANTS for v in variants):
        raise ApiError(400, "ai.err_variant")
    _need_key()                                                    # no key: say so now, not after the queue has been made
    batch = uuid.uuid4()
    with pool().connection() as conn:
        project = _project(conn, project_id)            # two requests at once for one calculation: one waits for the other (the write lock)
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
        conn.execute("DELETE FROM ai_image_jobs WHERE project_id = %s", (project_id,))                  # the finished ones of the last time
        for position, variant in enumerate(variants):
            conn.execute("INSERT INTO ai_image_jobs (project_id, batch_id, position, variant, description) VALUES (%s, %s, %s, %s, %s)",
                         (project_id, batch, position, variant, description))
        _log(conn, "info", "ai.log_queued", project=project, n=len(variants))
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
    return jsonify({"jobs": [_job_json(j) for j in jobs]}), 202


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


def _generate(key: str, model: str, quality: str, variant: str, description: str, source: bytes):
    response = _call("POST", f"{OPENAI}/images/edits", key,
                     data={"model": model, "prompt": build_prompt(variant, description), "size": VARIANTS[variant][0], "quality": quality, "n": "1"},
                     files={"image": ("photo.jpg", source, "image/jpeg")})
    try:
        encoded = response.json()["data"][0]["b64_json"]
        return _clean(base64.b64decode(encoded, validate=True))
    except (ApiError, ValueError, KeyError, IndexError, TypeError):
        raise AiError(502, "ai.err_bad_result", detail="no usable image in the answer") from None


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
        source = conn.execute("SELECT content FROM project_images WHERE project_id = %s AND kind = 'source'", (project_id,)).fetchone()
        if project is not None:
            _log(conn, "info", "ai.log_started", project=project, variant=job["variant"])
    if project is None:
        return False                                              # the calculation was deleted: its jobs went with it
    started = time.monotonic()
    try:
        key, model, quality = _need_key()
        if source is None:
            raise ApiError(400, "ai.err_no_photo")
        content, width, height = _generate(key, model, quality, job["variant"], job["description"], bytes(source["content"]))
    except ApiError as exc:
        return _failed(project_id, batch, job, project, exc)
    except Exception:
        log.exception("AI image job %s failed", job["id"])
        return _failed(project_id, batch, job, project, AiError(500, "ai.err_unexpected", detail="see the server log"))
    try:
        with pool().connection() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,)).fetchone() is None:
                return False
            conn.execute("INSERT INTO project_images (project_id, kind, variant, mime, content, width_px, height_px) "
                         "VALUES (%s, 'generated', %s, 'image/jpeg', %s, %s, %s)", (project_id, job["variant"], content, width, height))
            conn.execute("UPDATE ai_image_jobs SET status = 'done', finished_at = now(), updated_at = now() WHERE id = %s", (job["id"],))
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


# --- the log -------------------------------------------------------------------------------------------------------------

@bp.get("/ai-images/log")
def get_log():
    with pool().connection() as conn:
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


@bp.get("/project-images/<uuid:image_id>/file")
def image_file(image_id):
    with pool().connection() as conn:
        row = _image_row(conn, image_id, "id, kind, variant, mime, content, project_id")
        number = conn.execute("SELECT number FROM projects WHERE id = %s", (row["project_id"],)).fetchone()["number"]
    headers = {"Cache-Control": "no-store"}
    if request.args.get("download") == "1":
        name = f"berekening-{number}-{row['variant'] or 'foto'}.jpg"
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return Response(bytes(row["content"]), mimetype=row["mime"], headers=headers)


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

