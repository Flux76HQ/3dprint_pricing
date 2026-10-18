"""The logo on the invoice: one PNG or JPEG, uploaded under Settings and drawn at the top left of the built-in invoice (or put in a Word
template where it says `{{logo}}`). Like every upload it lives under UPLOAD_DIR with a generated name and is checked before it is kept:
only PNG and JPEG, a size cap, and a cap on the number of pixels (an image is decoded to measure it)."""
import hashlib
import os
import re
import uuid
from io import BytesIO
from pathlib import Path

from flask import Blueprint, Response, jsonify, request
from PIL import Image, UnidentifiedImageError

from .http import ApiError, config, login_required, pool

bp = Blueprint("invoice_logo", __name__, url_prefix="/api/invoice-logo")
MAX_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 25_000_000
FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpeg", "image/jpeg")}


class LogoError(Exception):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def _dir() -> Path:
    path = Path(config().upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def inspect(content: bytes) -> tuple:
    """(kind, width, height) of a PNG or JPEG; raises LogoError for anything else, for a damaged file and for a huge image."""
    if len(content) > MAX_BYTES:
        raise LogoError("invoice.err_logo_big")
    try:
        with Image.open(BytesIO(content)) as image:
            kind = FORMATS.get(image.format)
            width, height = image.size
            if kind is None:
                raise LogoError("invoice.err_logo_kind")
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise LogoError("invoice.err_logo_big")
            image.verify()
    except LogoError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise LogoError("invoice.err_logo_kind") from None
    return kind[0], width, height


def mimetype(kind: str) -> str:
    return "image/png" if kind == "png" else "image/jpeg"


def serialise(row) -> dict:
    return {"filename": row["filename"], "kind": row["kind"], "size_bytes": row["size_bytes"], "width_px": row["width_px"],
            "height_px": row["height_px"], "uploaded_at": row["uploaded_at"].isoformat()}


def load(conn) -> "dict | None":
    """The logo with its content, ready for the invoice; None when there is none (or its file went missing: an invoice without a logo
    is better than no invoice)."""
    row = conn.execute("SELECT * FROM invoice_logo").fetchone()
    if row is None:
        return None
    path = _dir() / row["stored_name"]
    if not path.is_file():
        return None
    return {**serialise(row), "content": path.read_bytes()}


def store_file(content: bytes, kind: str) -> str:
    stored = f"invoice-logo-{uuid.uuid4().hex}.{'png' if kind == 'png' else 'jpg'}"
    (_dir() / stored).write_bytes(content)
    return stored


def replace(conn, *, filename: str, kind: str, content: bytes, stored_name: str, width: int, height: int) -> "str | None":
    """Make this the logo; returns the stored name of the one it replaced (to delete once the transaction has committed)."""
    old = conn.execute("SELECT stored_name FROM invoice_logo").fetchone()
    conn.execute(
        "INSERT INTO invoice_logo (id, filename, kind, stored_name, size_bytes, sha256, width_px, height_px) VALUES (true, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET filename = EXCLUDED.filename, kind = EXCLUDED.kind, stored_name = EXCLUDED.stored_name, "
        "size_bytes = EXCLUDED.size_bytes, sha256 = EXCLUDED.sha256, width_px = EXCLUDED.width_px, height_px = EXCLUDED.height_px, uploaded_at = now()",
        (filename, kind, stored_name, len(content), hashlib.sha256(content).hexdigest(), width, height))
    return old["stored_name"] if old else None


def clean_filename(name, kind: str) -> str:
    cleaned = re.sub(r"[\\/\x00-\x1f]", "_", os.path.basename(str(name or "").replace("\\", "/")))[:200]
    return cleaned or f"logo.{kind}"


@bp.get("")
def get_logo():
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM invoice_logo").fetchone()
    return jsonify({"logo": serialise(row) if row else None})


@bp.post("")
def upload_logo():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError(400, "files.pick")
    content = upload.stream.read(MAX_BYTES + 1)
    try:
        kind, width, height = inspect(content)
    except LogoError as exc:
        raise ApiError(400, exc.key) from None
    stored = store_file(content, kind)
    try:
        with pool().connection() as conn:
            old = replace(conn, filename=clean_filename(upload.filename, kind), kind=kind, content=content, stored_name=stored,
                          width=width, height=height)
            row = conn.execute("SELECT * FROM invoice_logo").fetchone()
    except Exception:
        (_dir() / stored).unlink(missing_ok=True)
        raise
    if old:
        (_dir() / old).unlink(missing_ok=True)
    return jsonify({"logo": serialise(row)}), 201


@bp.delete("")
def delete_logo():
    with pool().connection() as conn:
        row = conn.execute("DELETE FROM invoice_logo RETURNING stored_name").fetchone()
    if row is not None:
        (_dir() / row["stored_name"]).unlink(missing_ok=True)
    return jsonify({"ok": True})


@bp.get("/file")
def logo_file():
    """The image itself, for the preview in Settings."""
    with pool().connection() as conn:
        logo = load(conn)
    if logo is None:
        raise ApiError(404, "invoice.err_logo_none")
    return Response(logo["content"], mimetype=mimetype(logo["kind"]), headers={"Cache-Control": "no-store"})
