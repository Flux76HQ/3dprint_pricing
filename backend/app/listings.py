"""What a 3D model is offered for sale as: its listing.

One per model: the title and the text of the advertisement, the price the owner asks, an EAN for a channel that wants one, and the photos
in the order they are shown. It is what a sales channel is given: today by hand (everything is put ready to place an advertisement, and
its address is kept with the model's links), later by a connection, which reads the same listing.

**The price is typed, never derived.** A calculation says what a model costs and what it should bring in; an advertisement says what was
agreed with the outside world, and a new filament price must not change that behind the owner's back. The screen shows the price the
calculation advises next to it.

**Photos are copies.** An own upload, or one of the model's product pictures taken over: both are kept in `listing_photos`, so making a
product picture again does not change an advertisement. An upload is untrusted like the others and goes through `ai_images._clean` (decoded,
turned upright, scaled down, written again as a JPEG: no metadata, no second payload). A stored photo never changes, so its id is its
validator and the browser may keep it (`http.keep_forever`).

Listings and their photos are the business's own data: they are in the backup and are read again on restore."""
import io
import re
import zipfile

from flask import Blueprint, Response, jsonify, request

from . import ai_images
from .api import _serialise, optional_number, text
from .http import ApiError, json_body, keep_forever, login_required, pool

bp = Blueprint("listings", __name__, url_prefix="/api")
MAX_PHOTOS = 12
MAX_TITLE, MAX_DESCRIPTION = 80, 4000
GTIN_LENGTHS = (8, 12, 13, 14)


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def ean(value) -> str:
    """An EAN (GTIN) as it is kept: its digits, or empty. The last digit is the check digit of the others (GS1): a typing mistake is refused."""
    digits = re.sub(r"[\s-]", "", str(value or ""))
    if not digits:
        return ""
    if not digits.isdigit() or len(digits) not in GTIN_LENGTHS:
        raise ApiError(400, "listing.err_ean")
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits[:-1])))
    if (10 - total % 10) % 10 != int(digits[-1]):
        raise ApiError(400, "listing.err_ean_check")
    return digits


def fields(body: dict) -> dict:
    """The fields of a listing, checked (also what a backup is read with)."""
    return {"title": text("f.listing_title", max_len=MAX_TITLE)(body.get("title")),
            "description": text("f.listing_description", required=False, max_len=MAX_DESCRIPTION)(body.get("description")),
            "price": optional_number("f.listing_price", maximum=1_000_000)(body.get("price")),
            "ean": ean(body.get("ean"))}


def clean(content: bytes) -> "tuple[bytes, int, int]":
    """A photo as it is kept (the same code and the same limits as a product photo)."""
    return ai_images._clean(content, jpeg_quality=90)


def add_photo(conn, project_id, content: bytes, width: int, height: int):
    count = conn.execute("SELECT count(*) AS n, COALESCE(max(position), 0) AS last FROM listing_photos WHERE project_id = %s", (project_id,)).fetchone()
    if count["n"] >= MAX_PHOTOS:
        raise ApiError(409, "listing.too_many_photos", max=MAX_PHOTOS)
    return conn.execute("INSERT INTO listing_photos (project_id, position, content, width_px, height_px) VALUES (%s, %s, %s, %s, %s) "
                        "RETURNING id, position, width_px, height_px", (project_id, count["last"] + 1, content, width, height)).fetchone()


def _project(conn, project_id):
    row = conn.execute("SELECT id, number, name FROM projects WHERE id = %s", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.calc_not_found")
    return row


def photos_of(conn, project_id) -> list:
    return conn.execute("SELECT id, position, width_px, height_px FROM listing_photos WHERE project_id = %s ORDER BY position, created_at, id", (project_id,)).fetchall()


def _present(conn, project_id) -> dict:
    listing = conn.execute("SELECT title, description, price, ean, created_at, updated_at FROM listings WHERE project_id = %s", (project_id,)).fetchone()
    return {"listing": _serialise(listing) if listing else None,
            "photos": [{**_serialise(p), "url": f"/api/listing-photos/{p['id']}/file"} for p in photos_of(conn, project_id)], "max_photos": MAX_PHOTOS}


@bp.get("/projects/<uuid:project_id>/listing")
def get_listing(project_id):
    with pool().read() as conn:
        _project(conn, project_id)
        return jsonify(_present(conn, project_id))


@bp.put("/projects/<uuid:project_id>/listing")
def put_listing(project_id):
    """Save the listing, and the order of its photos when `photos` names them: the ids in the order wanted. A photo that is left out is removed."""
    body = json_body()
    values = fields(body)
    order = body.get("photos")
    if order is not None and (not isinstance(order, list) or len(set(map(str, order))) != len(order)):
        raise ApiError(400, "listing.err_photos")
    with pool().connection() as conn:
        _project(conn, project_id)
        conn.execute("INSERT INTO listings (project_id, title, description, price, ean) VALUES (%s, %s, %s, %s, %s) "
                     "ON CONFLICT (project_id) DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description, price = EXCLUDED.price, "
                     "ean = EXCLUDED.ean, updated_at = now()", (project_id, values["title"], values["description"], values["price"], values["ean"]))
        if order is not None:
            known = {str(p["id"]) for p in photos_of(conn, project_id)}
            if not set(map(str, order)) <= known:
                raise ApiError(400, "listing.err_photos")
            for gone in known - set(map(str, order)):
                conn.execute("DELETE FROM listing_photos WHERE id = %s", (gone,))
            for position, photo_id in enumerate(order, 1):
                conn.execute("UPDATE listing_photos SET position = %s WHERE id = %s", (position, str(photo_id)))
        return jsonify(_present(conn, project_id))


@bp.delete("/projects/<uuid:project_id>/listing")
def delete_listing(project_id):
    """The model is no longer for sale: the listing and its photos go, the model and its product pictures stay."""
    with pool().connection() as conn:
        _project(conn, project_id)
        conn.execute("DELETE FROM listings WHERE project_id = %s", (project_id,))
        conn.execute("DELETE FROM listing_photos WHERE project_id = %s", (project_id,))
    return jsonify({"ok": True})


@bp.post("/projects/<uuid:project_id>/listing/photos")
def upload_photo(project_id):
    """Add a photo: an own file (`file`), or one of this model's product pictures taken over (`image_id` in a JSON body)."""
    upload = request.files.get("file")
    if upload is not None and upload.filename:
        content, width, height = clean(upload.stream.read(ai_images.MAX_PHOTO_BYTES * 2 + 1))
        with pool().connection() as conn:
            _project(conn, project_id)
            photo = add_photo(conn, project_id, content, width, height)
    else:
        image_id = (request.get_json(silent=True) or {}).get("image_id")
        if not image_id:
            raise ApiError(400, "files.pick")
        with pool().connection() as conn:
            _project(conn, project_id)
            image = conn.execute("SELECT content, width_px, height_px FROM project_images WHERE id = %s AND project_id = %s", (str(image_id), project_id)).fetchone()
            if image is None:
                raise ApiError(404, "err.not_found")
            photo = add_photo(conn, project_id, bytes(image["content"]), image["width_px"], image["height_px"])      # a copy: it stays as it is
    return jsonify({**_serialise(photo), "url": f"/api/listing-photos/{photo['id']}/file"}), 201


@bp.get("/listing-photos/<uuid:photo_id>/file")
def photo_file(photo_id):
    with pool().read() as conn:
        row = conn.execute("SELECT content FROM listing_photos WHERE id = %s", (photo_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    response = Response(bytes(row["content"]), mimetype="image/jpeg")
    response.set_etag(str(photo_id))                                  # written once and never changed: its id is its validator
    return keep_forever(response.make_conditional(request))


@bp.get("/projects/<uuid:project_id>/listing/photos.zip")
def photos_zip(project_id):
    """Every photo of the listing in one file, numbered in their order: what is uploaded by hand when an advertisement is placed."""
    with pool().read() as conn:
        project = _project(conn, project_id)
        rows = conn.execute("SELECT content FROM listing_photos WHERE project_id = %s ORDER BY position, created_at, id", (project_id,)).fetchall()
    if not rows:
        raise ApiError(404, "listing.no_photos")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:      # a JPEG does not get smaller
        for n, row in enumerate(rows, 1):
            archive.writestr(f"foto-{n:02d}.jpg", bytes(row["content"]))
    return Response(out.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="3d-model-{project["number"]}-fotos.zip"'})
