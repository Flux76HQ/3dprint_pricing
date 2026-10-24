"""Optional AI product images: a photo of the printed object goes to OpenAI's image model, which puts it in a realistic setting.

Everything here exists only when `AI_IMAGES_ENABLED=TRUE` in .env: the flag is checked on the server for every route (404 when
off), the browser merely follows `ai_images` in /api/auth/status. The OpenAI key is typed under Settings and kept encrypted with a key
derived from SESSION_SECRET (`passwords.seal`); it is never sent back, only its last four characters. Photos and results are kept in the
database (`project_images`, like the invoice logo) and re-encoded on the way in, so nothing from an upload is stored as it came."""
import base64
import re
from io import BytesIO

import requests
from flask import Blueprint, Response, jsonify, request
from PIL import Image, ImageOps, UnidentifiedImageError

from . import passwords
from .api import text
from .http import ApiError, RateLimiter, config, json_body, login_required, pool

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
    return jsonify(_public(saved))


@bp.delete("/ai-images/key")
def delete_key():
    with pool().connection() as conn:
        conn.execute("UPDATE ai_image_settings SET api_key_enc = NULL, updated_at = now()")
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


# --- talking to OpenAI -------------------------------------------------------------------------------------------

def _fail(response) -> ApiError:
    """A refusal from OpenAI as an error the owner can act on. The key and the request are never repeated."""
    try:
        error = (response.json() or {}).get("error") or {}
    except ValueError:
        error = {}
    code, reason = str(error.get("code") or ""), str(error.get("message") or "")[:200]
    if response.status_code == 401:
        return ApiError(400, "ai.err_key_invalid")
    if response.status_code == 429:
        return ApiError(429, "ai.err_quota" if code == "insufficient_quota" else "ai.err_busy")
    if code in ("moderation_blocked", "content_policy_violation"):
        return ApiError(422, "ai.err_policy")
    if response.status_code == 404:
        return ApiError(400, "ai.err_model_unknown")
    if response.status_code >= 500:
        return ApiError(502, "ai.err_upstream")
    return ApiError(400, "ai.err_rejected", reason=reason or str(response.status_code))


def _call(method: str, url: str, key: str, **kwargs):
    try:
        response = requests.request(method, url, headers={"Authorization": f"Bearer {key}"}, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), **kwargs)
    except requests.Timeout:
        raise ApiError(504, "ai.err_timeout") from None
    except requests.RequestException:
        raise ApiError(502, "ai.err_unreachable") from None
    if response.status_code >= 400:
        raise _fail(response)
    return response


@bp.post("/ai-images/test")
def test_connection():
    key, model, _quality = _need_key()
    _call("GET", f"{OPENAI}/models/{model}", key)
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
    row = conn.execute("SELECT id, object_description FROM projects WHERE id = %s", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.calc_not_found")
    return row


COLUMNS = "id, kind, variant, width_px, height_px, is_cover, created_at"


@bp.get("/projects/<uuid:project_id>/images")
def list_images(project_id):
    with pool().connection() as conn:
        _project(conn, project_id)
        rows = conn.execute(f"SELECT {COLUMNS} FROM project_images WHERE project_id = %s ORDER BY kind DESC, created_at, id",
                            (project_id,)).fetchall()
    return jsonify([_serialise(r) for r in rows])


@bp.post("/projects/<uuid:project_id>/images/source")
def upload_source(project_id):
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError(400, "ai.err_photo_pick")
    content, width, height = _clean(upload.stream.read(MAX_PHOTO_BYTES * 2 + 1))
    with pool().connection() as conn:
        _project(conn, project_id)
        conn.execute("DELETE FROM project_images WHERE project_id = %s AND kind = 'source'", (project_id,))
        row = conn.execute(
            f"INSERT INTO project_images (project_id, kind, mime, content, width_px, height_px) VALUES (%s, 'source', 'image/jpeg', %s, %s, %s) "
            f"RETURNING {COLUMNS}", (project_id, content, width, height)).fetchone()
    return jsonify(_serialise(row)), 201


@bp.post("/projects/<uuid:project_id>/images/generate")
def generate(project_id):
    body = json_body()
    variant = body.get("variant")
    if variant not in VARIANTS:
        raise ApiError(400, "ai.err_variant")
    key, model, quality = _need_key()
    with pool().connection() as conn:
        project = _project(conn, project_id)
        source = conn.execute("SELECT content FROM project_images WHERE project_id = %s AND kind = 'source'", (project_id,)).fetchone()
        count = conn.execute("SELECT count(*) AS n FROM project_images WHERE project_id = %s AND kind = 'generated'", (project_id,)).fetchone()["n"]
    if source is None:
        raise ApiError(400, "ai.err_no_photo")
    if count >= MAX_GENERATED:
        raise ApiError(409, "ai.err_too_many", max=MAX_GENERATED)
    description = body["description"] if "description" in body else project["object_description"]   # the form may hold text not yet saved
    description = text("f.object_description", required=False, max_len=500)(description)
    _limit.check("generate")

    size = VARIANTS[variant][0]
    response = _call("POST", f"{OPENAI}/images/edits", key,
                     data={"model": model, "prompt": build_prompt(variant, description), "size": size, "quality": quality, "n": "1"},
                     files={"image": ("photo.jpg", bytes(source["content"]), "image/jpeg")})
    try:
        encoded = response.json()["data"][0]["b64_json"]
        content, width, height = _clean(base64.b64decode(encoded, validate=True))
    except (ApiError, ValueError, KeyError, IndexError, TypeError):
        raise ApiError(502, "ai.err_bad_result") from None

    with pool().connection() as conn:
        _project(conn, project_id)                    # it may have been deleted while the model was working
        row = conn.execute(
            f"INSERT INTO project_images (project_id, kind, variant, mime, content, width_px, height_px) "
            f"VALUES (%s, 'generated', %s, 'image/jpeg', %s, %s, %s) RETURNING {COLUMNS}",
            (project_id, variant, content, width, height)).fetchone()
    return jsonify(_serialise(row)), 201


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
