"""Print files (STL / 3MF): upload, read what they say, download.

The file itself is stored under UPLOAD_DIR (a host-mounted path in Docker); the database holds
the metadata and what was read from it. A file that is uploaded but never linked to a calculation
is removed after a day.
"""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from . import printfile
from .http import ApiError, config, login_required, pool

bp = Blueprint("files", __name__, url_prefix="/api/print-files")
ALLOWED = (".stl", ".3mf")


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def _dir() -> Path:
    path = Path(config().upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def serialise(row) -> dict:
    return {"id": str(row["id"]), "filename": row["filename"], "kind": row["kind"],
            "size_bytes": row["size_bytes"], "created_at": row["created_at"].isoformat(),
            "analysis": row["analysis"]}


def _purge_orphans(conn) -> None:
    rows = conn.execute(
        "DELETE FROM print_files f WHERE f.created_at < now() - interval '1 day' "
        "AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.file_id = f.id) RETURNING stored_name"
    ).fetchall()
    for row in rows:
        (_dir() / row["stored_name"]).unlink(missing_ok=True)


@bp.post("")
def upload():
    upload_file = request.files.get("file")
    if upload_file is None or not upload_file.filename:
        raise ApiError(400, "Kies een .stl- of .3mf-bestand.")
    filename = re.sub(r"[\\/\x00-\x1f]", "_", os.path.basename(upload_file.filename.replace("\\", "/")))[:200]
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED:
        raise ApiError(400, "Alleen .stl en .3mf worden ondersteund.")

    stored = f"{uuid.uuid4().hex}{ext}"
    target = _dir() / stored
    tmp = _dir() / f".tmp-{uuid.uuid4().hex}"
    digest, size = hashlib.sha256(), 0
    try:
        with open(tmp, "wb") as out:
            for chunk in iter(lambda: upload_file.stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
        if size == 0:
            raise ApiError(400, "Het bestand is leeg.")
        try:
            analysis = printfile.analyze(tmp, ext)
        except printfile.PrintFileError as exc:
            raise ApiError(400, str(exc)) from None
        tmp.rename(target)
    finally:
        tmp.unlink(missing_ok=True)

    with pool().connection() as conn:
        row = conn.execute(
            "INSERT INTO print_files (filename, kind, size_bytes, sha256, stored_name, analysis) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (filename, ext[1:], size, digest.hexdigest(), stored, json.dumps(analysis))).fetchone()
        _purge_orphans(conn)
    return jsonify(serialise(row)), 201


def _get(file_id):
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM print_files WHERE id = %s", (file_id,)).fetchone()
    if row is None:
        raise ApiError(404, "Bestand niet gevonden.")
    return row


@bp.get("/<uuid:file_id>")
def metadata(file_id):
    return jsonify(serialise(_get(file_id)))


@bp.get("/<uuid:file_id>/download")
def download(file_id):
    row = _get(file_id)
    path = _dir() / row["stored_name"]
    if not path.is_file():
        raise ApiError(404, "Het bestand staat niet meer op de server.")
    return send_file(path, as_attachment=True, download_name=row["filename"],
                     mimetype="application/octet-stream")


@bp.get("/<uuid:file_id>/estimate")
def estimate(file_id):
    row = _get(file_id)
    volume = row["analysis"].get("volume_cm3")
    if not volume:
        raise ApiError(400, "Dit bestand bevat geen volume om een schatting op te baseren.")
    try:
        density = float(request.args.get("density", "1.24"))
        fill = float(request.args.get("fill", "40"))
    except ValueError:
        raise ApiError(400, "Dichtheid en vulling moeten getallen zijn.") from None
    if not 0.5 <= density <= 3 or not 1 <= fill <= 100:
        raise ApiError(400, "Dichtheid moet tussen 0,5 en 3 g/cm³ liggen en vulling tussen 1 en 100%.")
    return jsonify({"grams": printfile.estimate_grams(volume, density, fill), "density": density, "fill_pct": fill})


@bp.get("/materials")
def materials():
    return jsonify(printfile.DENSITIES)
