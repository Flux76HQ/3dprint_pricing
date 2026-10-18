"""The invoice template: one Word file with placeholders, or one PDF used as letter paper, uploaded under Settings.

The file itself is kept in the database (so it survives whatever happens to the uploads folder, and is part of every database backup)
together with what it is called and the margins of a PDF template; templates uploaded before that still have a file under UPLOAD_DIR,
which is moved into the database the first time it is read. Uploading a new one replaces the old one. Nothing here makes an invoice: see `invoice_docs` and `orders`.
"""
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request

from . import invoice_docs
from .api import optional_int
from .http import ApiError, config, json_body, login_required, pool

bp = Blueprint("invoice_template", __name__, url_prefix="/api/invoice-template")
KINDS = {".docx": "docx", ".pdf": "pdf"}
DEFAULT_TOP_MM, DEFAULT_BOTTOM_MM = 55, 25


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def _dir() -> Path:
    path = Path(config().upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def serialise(row) -> dict:
    return {"filename": row["filename"], "kind": row["kind"], "size_bytes": row["size_bytes"],
            "margin_top_mm": row["margin_top_mm"], "margin_bottom_mm": row["margin_bottom_mm"],
            "uploaded_at": row["uploaded_at"].isoformat()}


def load(conn) -> "dict | None":
    """The template with its content, ready for `invoice_docs.render_invoice`; None when there is none."""
    row = conn.execute("SELECT * FROM invoice_template").fetchone()
    if row is None:
        return None
    content = _content(conn, row)
    if content is None:
        raise ApiError(422, "invoice.err_template_gone")
    return {**serialise(row), "content": content}


def _content(conn, row) -> "bytes | None":
    """The bytes of the template: from the database, or from the file an earlier release left (then moved into the database)."""
    if row["content"] is not None:
        return bytes(row["content"])
    path = _dir() / row["stored_name"] if row["stored_name"] else None
    if path is None or not path.is_file():
        return None
    content = path.read_bytes()
    conn.execute("UPDATE invoice_template SET content = %s, stored_name = NULL WHERE id = true", (content,))
    path.unlink(missing_ok=True)
    return content


def validate(kind: str, content: bytes) -> None:
    """Raises `invoice_docs.InvoiceError` unless this can be used as a template of that kind."""
    if len(content) > invoice_docs.MAX_TEMPLATE_BYTES:
        raise invoice_docs.InvoiceError("invoice.err_too_big")
    if kind == "docx":
        invoice_docs.validate_docx(content)
    else:
        invoice_docs.validate_pdf(content)


def replace(conn, *, filename: str, kind: str, content: bytes, top: int, bottom: int) -> "str | None":
    """Make this the template; returns the stored name of an older file under UPLOAD_DIR that it replaced (to delete once the
    transaction has committed), if there was one."""
    old = conn.execute("SELECT stored_name FROM invoice_template").fetchone()
    conn.execute(
        "INSERT INTO invoice_template (id, filename, kind, content, size_bytes, sha256, margin_top_mm, margin_bottom_mm) "
        "VALUES (true, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET filename = EXCLUDED.filename, kind = EXCLUDED.kind, "
        "content = EXCLUDED.content, stored_name = NULL, size_bytes = EXCLUDED.size_bytes, sha256 = EXCLUDED.sha256, "
        "margin_top_mm = EXCLUDED.margin_top_mm, margin_bottom_mm = EXCLUDED.margin_bottom_mm, uploaded_at = now()",
        (filename, kind, content, len(content), hashlib.sha256(content).hexdigest(), top, bottom))
    return old["stored_name"] if old else None


def clean_filename(name: str, kind: str) -> str:
    cleaned = re.sub(r"[\\/\x00-\x1f]", "_", os.path.basename(str(name or "").replace("\\", "/")))[:200]
    return cleaned or f"template.{kind}"


def _ascii(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._ -]', "_", name)


def _margin(label: str, value, default: int) -> int:
    parsed = optional_int(label, minimum=0, maximum=200)(value)
    return default if parsed is None else parsed


@bp.get("")
def get_template():
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM invoice_template").fetchone()
    return jsonify({"template": serialise(row) if row else None, "placeholders": list(invoice_docs.PLACEHOLDERS),
                    "defaults": {"margin_top_mm": DEFAULT_TOP_MM, "margin_bottom_mm": DEFAULT_BOTTOM_MM}})


@bp.post("")
def upload_template():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError(400, "files.pick")
    kind = KINDS.get(os.path.splitext(upload.filename)[1].lower())
    if kind is None:
        raise ApiError(400, "invoice.err_kind")
    content = upload.stream.read(invoice_docs.MAX_TEMPLATE_BYTES + 1)
    magic_ok = content.startswith(b"%PDF") if kind == "pdf" else content.startswith(b"PK")
    if not content or not magic_ok:
        raise ApiError(400, "invoice.err_docx" if kind == "docx" else "invoice.err_pdf")
    top = _margin("f.margin_top", request.form.get("margin_top_mm"), DEFAULT_TOP_MM)
    bottom = _margin("f.margin_bottom", request.form.get("margin_bottom_mm"), DEFAULT_BOTTOM_MM)
    try:
        validate(kind, content)
    except invoice_docs.InvoiceError as exc:
        raise ApiError(400, exc.key, **exc.params) from None
    with pool().connection() as conn:
        old = replace(conn, filename=clean_filename(upload.filename, kind), kind=kind, content=content, top=top, bottom=bottom)
        row = conn.execute("SELECT * FROM invoice_template").fetchone()
    if old:
        (_dir() / old).unlink(missing_ok=True)
    return jsonify({"template": serialise(row)}), 201


@bp.patch("")
def set_margins():
    body = json_body()
    top = _margin("f.margin_top", body.get("margin_top_mm"), DEFAULT_TOP_MM)
    bottom = _margin("f.margin_bottom", body.get("margin_bottom_mm"), DEFAULT_BOTTOM_MM)
    with pool().connection() as conn:
        row = conn.execute("UPDATE invoice_template SET margin_top_mm = %s, margin_bottom_mm = %s RETURNING *", (top, bottom)).fetchone()
    if row is None:
        raise ApiError(404, "invoice.err_none")
    return jsonify({"template": serialise(row)})


@bp.delete("")
def delete_template():
    with pool().connection() as conn:
        row = conn.execute("DELETE FROM invoice_template RETURNING stored_name").fetchone()
    if row is not None and row["stored_name"]:
        (_dir() / row["stored_name"]).unlink(missing_ok=True)
    return jsonify({"ok": True})


@bp.get("/download")
def download():
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM invoice_template").fetchone()
        content = _content(conn, row) if row else None
    if row is None:
        raise ApiError(404, "invoice.err_none")
    if content is None:
        raise ApiError(404, "invoice.err_template_gone")
    return Response(content, mimetype="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{_ascii(row["filename"])}"; filename*=UTF-8\'\'{quote(row["filename"])}'})


@bp.get("/sample")
def sample():
    """A Word file with every placeholder in it, to start a template from."""
    return Response(invoice_docs.sample_docx(), mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": 'attachment; filename="factuur-sjabloon.docx"'})
