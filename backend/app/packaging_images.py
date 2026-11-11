"""A picture of a packaging item: a photo of the box or the bag, or its logo, so the right one is recognised at a glance.

One per item, optional. The upload is untrusted like every other: it is decoded, turned upright, scaled down and written again as a JPEG
(`ai_images._clean`, the same code as the product photos), so nothing of the original file is kept: no metadata such as where a phone
took it, and no second payload behind the image data. It lives in the database, never under UPLOAD_DIR, and is part of the backup."""
import hashlib

from flask import Blueprint, Response, jsonify, request

from . import ai_images
from .http import ApiError, login_required, pool

bp = Blueprint("packaging_images", __name__, url_prefix="/api/packaging-images")
MAX_EDGE = 800                           # shown small (a tile, a row of the list); this is sharp on any screen and keeps the database lean


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def clean(content: bytes) -> "tuple[bytes, int, int]":
    """The picture as it is kept: a JPEG of at most MAX_EDGE. Raises ApiError for what is not a usable picture."""
    return ai_images._clean(content, jpeg_quality=85, max_edge=MAX_EDGE)


def store(conn, packaging_id, content: bytes, width: int, height: int) -> str:
    """Make this the picture of the item; returns its version (what changes when the picture does, for the address the browser asks)."""
    digest = hashlib.sha256(content).hexdigest()
    conn.execute(
        "INSERT INTO packaging_images (packaging_id, content, sha256, width_px, height_px) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (packaging_id) DO UPDATE SET content = EXCLUDED.content, sha256 = EXCLUDED.sha256, width_px = EXCLUDED.width_px, "
        "height_px = EXCLUDED.height_px, updated_at = now()", (packaging_id, content, digest, width, height))
    return digest[:16]


@bp.get("")
def list_images():
    """Which items have a picture, and its version: the list of packaging asks this once instead of trying an address per item."""
    with pool().connection() as conn:
        rows = conn.execute("SELECT packaging_id, sha256 FROM packaging_images").fetchall()
    return jsonify({"images": {str(r["packaging_id"]): r["sha256"][:16] for r in rows}})


@bp.get("/<uuid:packaging_id>")
def get_image(packaging_id):
    with pool().connection() as conn:
        row = conn.execute("SELECT content FROM packaging_images WHERE packaging_id = %s", (packaging_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return Response(bytes(row["content"]), mimetype="image/jpeg")


@bp.put("/<uuid:packaging_id>")
def put_image(packaging_id):
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError(400, "files.pick")
    content, width, height = clean(upload.stream.read(ai_images.MAX_PHOTO_BYTES * 2 + 1))
    with pool().connection() as conn:
        if conn.execute("SELECT 1 FROM packaging_items WHERE id = %s", (packaging_id,)).fetchone() is None:
            raise ApiError(404, "err.not_found")
        version = store(conn, packaging_id, content, width, height)
    return jsonify({"version": version, "width_px": width, "height_px": height})


@bp.delete("/<uuid:packaging_id>")
def delete_image(packaging_id):
    with pool().connection() as conn:
        conn.execute("DELETE FROM packaging_images WHERE packaging_id = %s", (packaging_id,))
    return jsonify({"ok": True})
