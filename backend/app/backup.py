"""Backup and restore of everything the owner has entered: settings, printers, electricity tariffs, packaging, parts, accessories,
the filament library, filament rolls and calculations (optionally the uploaded print files too).

What is *not* in a backup, on purpose: passkeys, recovery codes, the password and its authenticator secret, and
notification subscriptions. They are credentials or belong to one device; a file that can be mailed around must not
be able to unlock the app. After a restore on a fresh install you sign in with a passkey as usual.

A restore replaces what is there, all or nothing: the whole file is checked first (with the same rules as typing the
data in by hand, and the calculations are recalculated), then everything is swapped in one transaction.
"""
import base64
import binascii
import hashlib
import json
import os
import re
import logging
import tempfile
import threading
import time
import uuid
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, current_app, g, jsonify, request, send_file

from . import ai_images, customers, filament_library, invoice_docs, invoice_logo, invoice_template, orders, printfile
from .api import RESOURCES, _project_fields, _serialise, _validated, stock_changed, validated_preferences
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, Localized, render, request_language

bp = Blueprint("backup", __name__, url_prefix="/api/backup")
log = logging.getLogger(__name__)

FORMAT = "printpricing-backup"
FORMAT_VERSION = 5          # 5: the filament library; 4: parts, accessories and optional order lines; 3: object descriptions, product images and the AI image model; 2: orders, the invoice template and calculation
                            # numbers. A file of an older version still restores
MAX_ROWS = 20_000
ARCHIVE_JSON = "backup.json"                 # the data of a backup with print files: a ZIP with this file and the models next to it, under files/
ZIP_MAGIC = b"PK\x03\x04"
MAX_STAGE_BYTES = 2 * 1024 ** 3              # a backup with print files is many uploads in one; the usual upload cap (MAX_UPLOAD_MB) is for one file
MAX_JSON_BYTES = 512 * 1024 ** 2             # what backup.json may unpack to
STAGE_PREFIX = ".restore-"                   # a backup waiting under UPLOAD_DIR for the owner to confirm; removed after the restore, or after an hour
STAGE_TTL_SECONDS = 3600
STALE_MINUTES = 15                           # a restore that has not moved for this long lost its thread (the container restarted); the swap is one transaction, so nothing had changed
# (key in the file, key in api.RESOURCES) -- the order is the order of insertion
SECTIONS = (("printers", "printers"), ("tariffs", "tariffs"), ("packaging", "packaging"), ("parts", "parts"),
            ("accessories", "accessories"), ("filament_library", "filament-library"), ("spools", "spools"))
PROJECT_COLUMNS = ("id", "number", "name", "notes", "object_description", "margin_pct", "vat_pct", "price_rounding", "data", "totals", "source_url",
                   "file_id", "stock_booked_at", "created_at", "updated_at")


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def _app_version() -> str:
    from . import VERSION, _commit
    return f"{VERSION} ({_commit()})"


# --- export -----------------------------------------------------------------------------------------------------

@bp.get("")
def export():
    include_files = request.args.get("files") == "1"
    began = time.monotonic()
    doc = {"format": FORMAT, "format_version": FORMAT_VERSION, "app_version": _app_version(),
           "created_at": datetime.now(timezone.utc).isoformat(), "includes_files": include_files}
    with pool().connection() as conn:
        prefs = conn.execute("SELECT preferences FROM users WHERE id = %s", (g.user_id,)).fetchone()
        doc["preferences"] = (prefs or {}).get("preferences") or {}
        for key, resource in SECTIONS:
            table, fields, _order = (*RESOURCES[resource][:2], None)
            columns = ["id", *fields, "created_at"]
            rows = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY created_at, id").fetchall()
            doc[key] = [_serialise(r) for r in rows]
        rows = conn.execute(f"SELECT {', '.join(PROJECT_COLUMNS)} FROM projects ORDER BY created_at, id").fetchall()
        doc["projects"] = [_serialise(r) for r in rows]
        doc["customers"] = [_serialise(r) for r in conn.execute(
            f"SELECT id, {', '.join(customers.FIELDS)}, created_at, updated_at FROM customers ORDER BY created_at, id").fetchall()]
        doc["orders"] = _export_orders(conn)
        doc["invoice_pdfs"] = [{"order_id": str(r["order_id"]), "invoice_number": r["invoice_number"],
                                "content_b64": base64.b64encode(bytes(r["content"])).decode("ascii")}
                               for r in conn.execute("SELECT order_id, invoice_number, content FROM invoice_pdfs ORDER BY created_at, order_id").fetchall()]
        try:
            template = invoice_template.load(conn)
        except ApiError:                                             # the file went missing: the rest of the backup is still worth having
            template = None
        doc["project_images"] = [
            {"project_id": str(r["project_id"]), "kind": r["kind"], "variant": r["variant"], "is_cover": r["is_cover"],
             "created_at": r["created_at"].isoformat(), "content_b64": base64.b64encode(bytes(r["content"])).decode("ascii")}
            for r in conn.execute("SELECT project_id, kind, variant, is_cover, created_at, content FROM project_images "
                                  "ORDER BY created_at, id").fetchall()]
        ai = conn.execute("SELECT model, quality FROM ai_image_settings").fetchone()      # never the API key
        if ai:
            doc["ai_image_settings"] = {"model": ai["model"], "quality": ai["quality"]}
        logo = invoice_logo.load(conn)
        if logo:
            doc["invoice_logo"] = {"filename": logo["filename"], "kind": logo["kind"], "content_b64": base64.b64encode(logo["content"]).decode("ascii")}
        if template:
            doc["invoice_template"] = {"filename": template["filename"], "kind": template["kind"], "margin_top_mm": template["margin_top_mm"],
                                       "margin_bottom_mm": template["margin_bottom_mm"],
                                       "content_b64": base64.b64encode(template["content"]).decode("ascii")}
        attachments = []                                             # (name in the ZIP, path on disk, kind)
        if include_files:
            files, used = [], set()
            for row in conn.execute("SELECT * FROM print_files ORDER BY created_at, id").fetchall():
                path = Path(config().upload_dir) / row["stored_name"]
                if not path.is_file():
                    continue                                         # the row outlived its file: nothing to back up
                member = _archive_name(row["filename"], used)
                attachments.append((member, path, row["kind"]))
                files.append({"id": str(row["id"]), "filename": row["filename"], "kind": row["kind"],
                              "sha256": row["sha256"], "created_at": row["created_at"].isoformat(),
                              "archive_path": member})                # the model itself sits in the ZIP, as a file of its own
            doc["files"] = files
    queried = time.monotonic() - began
    stamp = datetime.now().strftime("%Y-%m-%d")
    if not include_files:
        log.info("backup: read in %.1fs", queried)
        return Response(json.dumps(doc, ensure_ascii=False), mimetype="application/json",
                        headers={"Content-Disposition": f'attachment; filename="printpricing-backup-{stamp}.json"'})
    upload_dir = Path(config().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    out = tempfile.TemporaryFile(dir=upload_dir)                     # on the data disk, not in memory: the models can be large
    with zipfile.ZipFile(out, "w", strict_timestamps=False) as archive:
        archive.writestr(ARCHIVE_JSON, json.dumps(doc, ensure_ascii=False), compress_type=zipfile.ZIP_DEFLATED)
        for member, path, _kind in attachments:                      # stored, not deflated: a 3MF is a ZIP already, and deflating an STL costs far more time on a small server than the space it saves
            archive.write(path, member, compress_type=zipfile.ZIP_STORED)
    size = out.seek(0, os.SEEK_END)
    out.seek(0)
    response = send_file(out, mimetype="application/zip", as_attachment=True, download_name=f"printpricing-backup-{stamp}.zip")      # with its size, so the screen can show how far the download is
    response.headers["Content-Disposition"] = f'attachment; filename="printpricing-backup-{stamp}.zip"'
    response.headers["Content-Length"] = str(size)
    log.info("backup with files: read in %.1fs, zipped in %.1fs, %.1f MB", queried, time.monotonic() - began - queried, size / 1048576)
    return response


def _archive_name(filename: str, used: set) -> str:
    """Where a model goes in the ZIP: files/<its own name>, with (2), (3)… when two models are called the same."""
    name = re.sub(r"[\\/\x00-\x1f]", "_", os.path.basename(str(filename or "").replace("\\", "/"))).strip(". ") or "model"
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while candidate.casefold() in used:
        n += 1
        candidate = f"{stem} ({n}){ext}"
    used.add(candidate.casefold())
    return f"files/{candidate}"


MAX_INVOICE_PDF_BYTES = 10 * 1024 * 1024
ORDER_COLUMNS = ("id", "number", "customer_id", "invoice_number", "invoice_date", "created_at", "updated_at", *orders.ORDER_FIELDS)


def _export_orders(conn) -> list:
    out = []
    rows = conn.execute(f"SELECT {', '.join(ORDER_COLUMNS)} FROM orders ORDER BY number").fetchall()
    lines = orders._lines_of(conn, [r["id"] for r in rows])
    for row in rows:
        item = _serialise(row)
        item["lines"] = [_serialise({k: line[k] for k in ("project_id", "project_number", "description", "quantity", "unit_price", "vat_pct", "cost_price", "margin_pct", "optional")})
                         for line in lines[row["id"]]]
        out.append(item)
    return out


# --- restore ----------------------------------------------------------------------------------------------------

def _uuid(value, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise Localized("backup.bad_id") from None


def _when(value, default=None):
    if value in (None, ""):
        return default
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise Localized("backup.bad_date") from None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _rows(doc: dict, key: str) -> list:
    rows = doc.get(key, [])
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ApiError(400, "backup.bad_section", section=L(f"backup.s.{key}"))
    return rows


def _row_error(key: str, n: int, error) -> ApiError:
    reason = error.msg if hasattr(error, "msg") else str(error)
    return ApiError(400, "backup.bad_row", section=L(f"backup.s.{key}"), n=n, reason=reason)


def _parse(doc, archive=None, progress=None) -> dict:
    """Check the whole file and turn it into what will be written. Nothing is written here. `archive` is the ZIP the models sit in, if any."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ApiError(400, "backup.not_backup")
    version = doc.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ApiError(400, "backup.not_backup")
    if version > FORMAT_VERSION:
        raise ApiError(400, "backup.too_new", version=str(doc.get("app_version", "?"))[:40])
    plan = {"sections": {}, "files": [], "file_ids": set()}

    try:
        plan["preferences"] = validated_preferences(doc.get("preferences") if isinstance(doc.get("preferences"), dict) else {})
    except ApiError as exc:
        raise _row_error("preferences", 1, exc) from None

    if doc.get("includes_files") and isinstance(doc.get("files"), list):
        entries = _rows(doc, "files")
        for n, entry in enumerate(entries, 1):
            if progress:
                progress(n, len(entries))                          # reading a model again is the slow part: this is what the screen counts
            try:
                plan["files"].append(_parse_file(entry, archive))
            except (ApiError, Localized, printfile.PrintFileError) as exc:
                raise _row_error("files", n, exc) from None
        plan["file_ids"] = {f["id"] for f in plan["files"]}

    for key, resource in SECTIONS:
        table, fields = RESOURCES[resource][:2]
        parsed = []
        for n, row in enumerate(_rows(doc, key), 1):
            try:
                if not isinstance(row, dict):
                    raise Localized("backup.bad_row_type")
                values = _validated(fields, row, partial=False)
                parsed.append({"id": _uuid(row.get("id") or uuid.uuid4(), key), "values": values,
                               "created_at": _when(row.get("created_at"))})
            except (ApiError, Localized) as exc:
                raise _row_error(key, n, exc) from None
        if key == "filament_library":
            clash = filament_library.first_clash([item["values"] for item in parsed])       # a backup must not bring back what the library refuses
            if clash:
                raise _row_error(key, clash[0], Localized("library.duplicate", name=filament_library.name_of(clash[1])))
        if key == "tariffs":
            seen = False
            for item in parsed:                                     # at most one default (the database insists)
                if item["values"].get("is_default"):
                    item["values"]["is_default"] = not seen
                    seen = True
        plan["sections"][key] = (table, parsed)

    projects = []
    for n, row in enumerate(_rows(doc, "projects"), 1):
        try:
            if not isinstance(row, dict):
                raise Localized("backup.bad_row_type")
            body = {k: v for k, v in row.items() if k != "file_id"}
            fields = _project_fields(body)                         # validates and recalculates the totals
            fields["file_id"] = str(row["file_id"]) if row.get("file_id") else None
            projects.append({"id": _uuid(row.get("id") or uuid.uuid4(), "projects"), "fields": fields,
                             "stock_booked_at": _when(row.get("stock_booked_at")),
                             "created_at": _when(row.get("created_at")), "updated_at": _when(row.get("updated_at"))})
        except (ApiError, Localized) as exc:
            raise _row_error("projects", n, exc) from None
    _number_projects(projects, doc)
    plan["projects"] = projects
    plan["project_images"] = _parse_project_images(doc.get("project_images"), {p["id"] for p in projects})
    plan["ai_settings"] = _parse_ai_settings(doc.get("ai_image_settings"))
    plan["orders"] = _parse_orders(doc)
    plan["customers"] = _parse_customers(doc, plan["orders"])
    plan["invoice_pdfs"] = _parse_invoice_pdfs(doc.get("invoice_pdfs"), plan["orders"])
    plan["template"] = _parse_template(doc.get("invoice_template"))
    plan["logo"] = _parse_logo(doc.get("invoice_logo"))
    return plan


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 2_000_000_000:
        return None
    return value


def _number_projects(projects: list, doc: dict) -> None:
    """Calculations keep their numbers; one without (a version 1 file) gets the next free one, in the order of the file."""
    given = [_positive_int(row.get("number")) if isinstance(row, dict) else None for row in doc.get("projects", [])]
    used = [n for n in given if n]
    if len(used) != len(set(used)):
        raise _row_error("projects", 1, Localized("backup.bad_number"))
    free = max(used, default=0)
    for project, number in zip(projects, given):
        if number is None:
            free += 1
            number = free
        project["number"] = number


def _parse_orders(doc: dict) -> list:
    parsed, numbers, invoices = [], set(), set()
    for n, row in enumerate(_rows(doc, "orders"), 1):
        try:
            if not isinstance(row, dict):
                raise Localized("backup.bad_row_type")
            values = orders.validated_order(row)
            for line, raw in zip(values["lines"], row.get("lines", [])):
                line["project_number"] = _positive_int(raw.get("project_number")) if isinstance(raw, dict) else None
            number = _positive_int(row.get("number"))
            invoice = row.get("invoice_number") or None
            if number is None or number in numbers or (invoice is not None and (not isinstance(invoice, str) or len(invoice) > 40 or invoice in invoices)):
                raise Localized("backup.bad_number")
            numbers.add(number)
            if invoice:
                invoices.add(invoice)
            parsed.append({"id": _uuid(row.get("id") or uuid.uuid4(), "orders"), "number": number, "values": values, "invoice_number": invoice,
                           "customer_id": _uuid(row["customer_id"], "orders") if row.get("customer_id") else None,
                           "invoice_date": values["invoice_date"] if invoice else None, "created_at": _when(row.get("created_at")),
                           "updated_at": _when(row.get("updated_at"))})
        except (ApiError, Localized) as exc:
            raise _row_error("orders", n, exc) from None
    return parsed


def _parse_customers(doc: dict, parsed_orders: list) -> list:
    """The customers of the file. An order that names no (known) customer, as in a file from before customers existed, gets one made
    from the details it carries: one per name + customer number, with the next free whole number where that number is empty or taken."""
    out, by_id, numbers = [], {}, set()
    for n, row in enumerate(_rows(doc, "customers"), 1):
        try:
            if not isinstance(row, dict):
                raise Localized("backup.bad_row_type")
            values = customers.validated_customer(row)
            cid = _uuid(row.get("id"), "customers")
            if not values["number"] or values["number"].lower() in numbers or cid in by_id:
                raise Localized("backup.bad_number")
            numbers.add(values["number"].lower())
            item = {"id": cid, "values": values, "created_at": _when(row.get("created_at")), "updated_at": _when(row.get("updated_at"))}
            by_id[cid] = item
            out.append(item)
        except (ApiError, Localized) as exc:
            raise _row_error("customers", n, exc) from None
    made, free = {}, 1
    for order in parsed_orders:
        if order["customer_id"] in by_id:
            continue
        v = order["values"]
        key = (v["customer_name"].lower(), v["customer_number"].lower())
        if key not in made:
            number = v["customer_number"]
            while not number or number.lower() in numbers:
                number, free = str(free), free + 1
            numbers.add(number.lower())
            cid = uuid.uuid4()
            item = {"id": cid, "created_at": None, "updated_at": None, "values": {
                "number": number, "name": v["customer_name"], "address": v["address"], "postal_code": v["postal_code"], "city": v["city"],
                "country": v["country"], "email": v["email"], "phone": v["phone"], "notes": ""}}
            made[key] = cid
            out.append(item)
        order["customer_id"] = made[key]
        order["values"]["customer_number"] = next(c["values"]["number"] for c in out if c["id"] == made[key])
    return out


def _parse_invoice_pdfs(entries, parsed_orders: list) -> list:
    """The kept invoice PDFs that belong to an order (with that invoice number) of this file; any other one is let go."""
    if not entries:
        return []
    if not isinstance(entries, list):
        raise _row_error("invoice_pdfs", 1, Localized("backup.bad_row_type"))
    numbers = {o["id"]: o["invoice_number"] for o in parsed_orders if o["invoice_number"]}
    out, seen = [], set()
    for n, entry in enumerate(entries, 1):
        try:
            if not isinstance(entry, dict):
                raise Localized("backup.bad_row_type")
            order_id = _uuid(entry.get("order_id"), "invoice_pdfs")
            try:
                content = base64.b64decode(str(entry.get("content_b64", "")), validate=True)
            except (binascii.Error, ValueError):
                raise Localized("backup.bad_file") from None
            if not content.startswith(b"%PDF") or len(content) > MAX_INVOICE_PDF_BYTES:
                raise Localized("backup.bad_file")
        except (ApiError, Localized) as exc:
            raise _row_error("invoice_pdfs", n, exc) from None
        if numbers.get(order_id) and numbers[order_id] == entry.get("invoice_number") and order_id not in seen:
            seen.add(order_id)
            out.append({"order_id": order_id, "invoice_number": numbers[order_id], "content": content})
    return out


def _parse_project_images(entries, project_ids: set) -> list:
    if entries in (None, []):
        return []
    if not isinstance(entries, list) or len(entries) > MAX_ROWS:
        raise _row_error("project_images", 1, Localized("backup.bad_section", section=L("backup.s.project_images")))
    items, covers, sources = [], set(), set()
    for n, entry in enumerate(entries, 1):
        try:
            if not isinstance(entry, dict) or entry.get("kind") not in ("source", "generated"):
                raise Localized("backup.bad_row_type")
            project_id = _uuid(entry.get("project_id"), "project_images")
            if project_id not in project_ids:
                raise Localized("backup.bad_row_type")
            variant = entry.get("variant")
            if entry["kind"] == "generated" and variant not in ai_images.VARIANTS:
                raise Localized("backup.bad_row_type")
            try:
                content = base64.b64decode(str(entry.get("content_b64", "")), validate=True)
            except (binascii.Error, ValueError):
                raise Localized("backup.bad_file") from None
            content, width, height = ai_images._clean(content)                      # read again, never taken on trust from the file
            is_cover = entry.get("is_cover") is True and project_id not in covers
            if entry["kind"] == "source":
                if project_id in sources:
                    raise Localized("backup.bad_row_type")
                sources.add(project_id)
            if is_cover:
                covers.add(project_id)
            items.append({"project_id": project_id, "kind": entry["kind"], "variant": variant if entry["kind"] == "generated" else None,
                          "is_cover": is_cover, "created_at": _when(entry.get("created_at")), "content": content, "width": width, "height": height})
        except (ApiError, Localized) as exc:
            raise _row_error("project_images", n, exc) from None
    return items


def _parse_ai_settings(entry):
    if entry in (None, {}):
        return None
    if not isinstance(entry, dict) or entry.get("quality") not in ai_images.QUALITIES or not ai_images.MODEL.match(str(entry.get("model", ""))):
        raise _row_error("ai_image_settings", 1, Localized("backup.bad_row_type"))
    return {"model": entry["model"], "quality": entry["quality"]}


def _parse_logo(entry):
    if entry in (None, {}):
        return None
    try:
        if not isinstance(entry, dict):
            raise Localized("backup.bad_row_type")
        try:
            content = base64.b64decode(str(entry.get("content_b64", "")), validate=True)
        except (binascii.Error, ValueError):
            raise Localized("backup.bad_file") from None
        try:
            kind, width, height = invoice_logo.inspect(content)                 # read again, never taken on trust from the file
        except invoice_logo.LogoError as exc:
            raise Localized(exc.key) from None
        return {"filename": invoice_logo.clean_filename(entry.get("filename"), kind), "kind": kind, "content": content, "width": width, "height": height}
    except (ApiError, Localized) as exc:
        raise _row_error("logo", 1, exc) from None


def _parse_template(entry):
    if entry in (None, {}):
        return None
    try:
        if not isinstance(entry, dict) or entry.get("kind") not in ("docx", "pdf"):
            raise Localized("backup.bad_row_type")
        try:
            content = base64.b64decode(str(entry.get("content_b64", "")), validate=True)
        except (binascii.Error, ValueError):
            raise Localized("backup.bad_file") from None
        try:
            invoice_template.validate(entry["kind"], content)
        except invoice_docs.InvoiceError as exc:
            raise Localized(exc.key, **exc.params) from None
        margins = [invoice_template._margin(label, entry.get(key), default) for label, key, default in
                   (("f.margin_top", "margin_top_mm", invoice_template.DEFAULT_TOP_MM), ("f.margin_bottom", "margin_bottom_mm", invoice_template.DEFAULT_BOTTOM_MM))]
        return {"filename": invoice_template.clean_filename(entry.get("filename"), entry["kind"]), "kind": entry["kind"], "content": content,
                "top": margins[0], "bottom": margins[1]}
    except (ApiError, Localized) as exc:
        raise _row_error("template", 1, exc) from None


def _read_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """One file out of the ZIP, never more than `limit` bytes: what the ZIP says it unpacks to is not taken on trust."""
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise Localized("backup.missing_file", name=name[:120]) from None
    if info.file_size > limit:
        raise Localized("backup.bad_file")
    try:
        with archive.open(info) as handle:
            data = handle.read(limit + 1)
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError):
        raise Localized("backup.bad_file") from None
    if len(data) > limit:
        raise Localized("backup.bad_file")
    return data


def _parse_file(entry, archive=None) -> dict:
    if not isinstance(entry, dict):
        raise Localized("backup.bad_row_type")
    kind = entry.get("kind")
    if kind not in ("stl", "3mf"):
        raise Localized("pf.unsupported")
    member = entry.get("archive_path")
    if member is not None:
        if archive is None or not isinstance(member, str):
            raise Localized("backup.bad_file")
        content = _read_member(archive, member, config().max_upload_mb * 1024 * 1024)      # a model never was bigger than an upload may be
    else:
        try:
            content = base64.b64decode(str(entry.get("content_b64", "")), validate=True)
        except (binascii.Error, ValueError):
            raise Localized("backup.bad_file") from None
    if not content:
        raise Localized("files.empty")
    digest = hashlib.sha256(content).hexdigest()
    if entry.get("sha256") and entry["sha256"] != digest:
        raise Localized("backup.bad_file")                          # damaged or edited: the checksum no longer fits
    filename = re.sub(r"[\\/\x00-\x1f]", "_", os.path.basename(str(entry.get("filename") or f"model.{kind}").replace("\\", "/")))[:200]
    tmp = Path(config().upload_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    tmp = tmp / f".tmp-{uuid.uuid4().hex}"
    try:
        tmp.write_bytes(content)
        analysis = printfile.analyze(tmp, f".{kind}")              # read again, never taken on trust from the file
    finally:
        tmp.unlink(missing_ok=True)
    return {"id": str(_uuid(entry.get("id") or uuid.uuid4(), "files")), "filename": filename or f"model.{kind}", "kind": kind,
            "member": member, "content": content if member is None else None,       # from the ZIP it is read again when written: not all the models in memory at once
            "size": len(content), "sha256": digest, "analysis": analysis, "created_at": _when(entry.get("created_at"))}


def _summary(plan: dict) -> dict:
    return {"printers": len(plan["sections"]["printers"][1]), "tariffs": len(plan["sections"]["tariffs"][1]),
            "packaging": len(plan["sections"]["packaging"][1]),
            "parts": len(plan["sections"]["parts"][1]), "accessories": len(plan["sections"]["accessories"][1]), "spools": len(plan["sections"]["spools"][1]),
            "library": len(plan["sections"]["filament_library"][1]),
            "projects": len(plan["projects"]), "files": len(plan["files"]), "preferences": len(plan["preferences"]),
            "orders": len(plan["orders"]), "customers": len(plan["customers"]), "template": 1 if plan["template"] else 0, "logo": 1 if plan["logo"] else 0,
            "images": len(plan["project_images"])}


def _insert(conn, table: str, values: dict) -> None:
    columns = list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
                 tuple(values.values()))


def _restore_orders(conn, items: list) -> None:
    for item in items:
        v = item["values"]
        columns = {"id": item["id"], "number": item["number"], "customer_id": item["customer_id"], "invoice_number": item["invoice_number"],
                   "invoice_date": item["invoice_date"],
                   **{f: v[f] for f in orders.ORDER_FIELDS}}
        for key in ("created_at", "updated_at"):
            if item[key]:
                columns[key] = item[key]
        _insert(conn, "orders", columns)
        orders._write_lines(conn, item["id"], v["lines"])
    conn.execute(f"ALTER SEQUENCE order_number_seq RESTART WITH {max((i['number'] for i in items), default=0) + 1}")
    counters: dict[int, int] = {}
    for item in items:                                              # the next invoice number carries on after the highest one restored
        found = re.fullmatch(r"(\d{4})-(\d+)", item["invoice_number"] or "")
        if found:
            year, last = int(found.group(1)), int(found.group(2))
            counters[year] = max(counters.get(year, 0), last)
    for year, last in counters.items():
        conn.execute("INSERT INTO invoice_counters (year, last) VALUES (%s, %s)", (year, last))


# --- staging: a backup is sent once, checked, and restored from the server's disk after the owner confirmed ------

def _upload_dir() -> Path:
    path = Path(config().upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _staged(token) -> Path:
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ApiError(400, "backup.expired")
    path = _upload_dir() / f"{STAGE_PREFIX}{token}"
    if not path.is_file():
        raise ApiError(400, "backup.expired")
    return path


def _clear_old_stages() -> None:
    for path in _upload_dir().glob(f"{STAGE_PREFIX}*"):
        try:
            if time.time() - path.stat().st_mtime > STAGE_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _open_backup(path: Path):
    """The data of a staged backup: a ZIP (backup.json and the models) or a plain JSON file. Resolves (document, archive or None)."""
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic == ZIP_MAGIC:
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise ApiError(400, "backup.bad_zip") from None
        try:
            doc = json.loads(_read_member(archive, ARCHIVE_JSON, MAX_JSON_BYTES))
        except Localized:
            archive.close()
            raise ApiError(400, "backup.not_backup") from None
        except ValueError:
            archive.close()
            raise ApiError(400, "backup.not_json") from None
        return doc, archive
    try:
        return json.loads(path.read_bytes()), None
    except ValueError:                                              # includes a file that is not text at all
        raise ApiError(400, "backup.not_json") from None


def _summary_of(doc, plan: dict) -> dict:
    doc = doc if isinstance(doc, dict) else {}
    return {**_summary(plan), "app_version": str(doc.get("app_version", ""))[:40],
            "created_at": str(doc.get("created_at", ""))[:40], "includes_files": bool(plan["files"])}


@bp.post("/stage")
def stage():
    """Takes the backup (the raw request body: a ZIP or a JSON file), keeps it on the server's disk and checks all of it.
    The answer says what would come back and gives the token that /restore needs. Nothing in the database changes."""
    request.max_content_length = MAX_STAGE_BYTES
    _clear_old_stages()
    token = uuid.uuid4().hex
    path = _upload_dir() / f"{STAGE_PREFIX}{token}"
    try:
        with path.open("wb") as handle:
            while True:
                chunk = request.stream.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except Exception as exc:                                        # werkzeug raises its own error when the limit is passed
        path.unlink(missing_ok=True)
        if getattr(exc, "code", None) == 413:
            raise ApiError(413, "backup.too_large", mb=MAX_STAGE_BYTES // 1024 ** 2) from None
        raise
    archive = None
    try:
        doc, archive = _open_backup(path)
        summary = _summary_of(doc, _parse(doc, archive))
    except Exception:
        path.unlink(missing_ok=True)                                # a file that is refused is not kept
        raise
    finally:
        if archive:
            archive.close()
    return jsonify({"ok": True, "token": token, "summary": summary})


@bp.delete("/stage/<token>")
def unstage(token):
    """The owner changed their mind after the check."""
    try:
        _staged(token).unlink(missing_ok=True)
    except ApiError:
        pass
    return jsonify({"ok": True})


@bp.post("/restore")
def restore():
    """The backup as the JSON body, done within this request. The screen uses stage + jobs instead (a restore that survives leaving the page)."""
    doc = json_body()
    plan = _parse(doc)
    summary = _summary_of(doc, plan)
    if request.args.get("dry_run") == "1":
        return jsonify({"ok": True, "dry_run": True, "summary": summary})
    _write(plan, None, g.user_id)
    stock_changed()                                                   # the restored shelf and thresholds may already be low
    return jsonify({"ok": True, "dry_run": False, "summary": summary})


# --- the restore as a background job -------------------------------------------------------------------------------

JOB_LOCK = 7603003                   # two clicks never start two restores


def _job_json(row) -> dict:
    message = render(L(row["error_key"], **row["error_params"]), request_language()) if row["error_key"] else None
    return {"id": str(row["id"]), "status": row["status"], "phase": row["phase"], "step": row["step"], "steps": row["steps"],
            "message": message, "summary": row["summary"],
            "checking_seconds": row["checking_seconds"], "replacing_seconds": row["replacing_seconds"], "started_at": row["created_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None}


def _recover(conn) -> None:
    """Give up on a restore that has not moved for a while: its thread died with its container. The swap is one transaction, so nothing changed."""
    conn.execute("UPDATE backup_jobs SET status = 'failed', error_key = 'backup.err_interrupted', finished_at = now(), updated_at = now() "
                 "WHERE status = 'running' AND updated_at < now() - make_interval(mins => %s)", (STALE_MINUTES,))


def _progress(job_id, phase: str, step: int, steps: int) -> None:
    with pool().connection() as conn:
        conn.execute("UPDATE backup_jobs SET phase = %s, step = %s, steps = %s, updated_at = now() WHERE id = %s AND status = 'running'",
                     (phase, step, steps, job_id))


@bp.get("/jobs/latest")
def latest_job():
    """The restore that is running, or the last one that finished and has not been dismissed. The screen polls this."""
    with pool().connection() as conn:
        _recover(conn)
        row = conn.execute("SELECT * FROM backup_jobs ORDER BY created_at DESC LIMIT 1").fetchone()
    return jsonify({"job": _job_json(row) if row else None})


@bp.post("/jobs")
def start_job():
    """Restore the staged backup in the background and answer at once. From here on nothing depends on this browser: leaving the page does not stop it."""
    staged = _staged(json_body().get("token"))
    with pool().connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (JOB_LOCK,))
        _recover(conn)
        if conn.execute("SELECT 1 FROM backup_jobs WHERE status = 'running'").fetchone():
            raise ApiError(409, "backup.busy")
        conn.execute("DELETE FROM backup_jobs")                          # the last one is dismissed by starting the next
        row = conn.execute("INSERT INTO backup_jobs DEFAULT VALUES RETURNING *").fetchone()
    _start(current_app._get_current_object(), row["id"], staged.name[len(STAGE_PREFIX):], g.user_id, request_language())
    return jsonify({"job": _job_json(row)}), 202


@bp.delete("/jobs/<uuid:job_id>")
def dismiss_job(job_id):
    with pool().connection() as conn:
        conn.execute("DELETE FROM backup_jobs WHERE id = %s AND status <> 'running'", (job_id,))
    return jsonify({"ok": True})


def _start(app, job_id, token, user_id, lang):
    """Restore in a thread of this web worker (tests replace this to run it on the spot)."""
    thread = threading.Thread(target=_run_restore, args=(app, job_id, token, user_id, lang), name="backup-restore", daemon=True)
    thread.start()
    return thread


def _run_restore(app, job_id, token, user_id, lang) -> None:
    with app.app_context():
        staged = _upload_dir() / f"{STAGE_PREFIX}{token}"
        archive = None
        try:
            began = time.monotonic()
            doc, archive = _open_backup(staged)
            plan = _parse(doc, archive, progress=lambda n, total: _progress(job_id, "checking", n, total))
            summary = _summary_of(doc, plan)
            checked = round(time.monotonic() - began, 1)
            with pool().connection() as conn:
                conn.execute("UPDATE backup_jobs SET checking_seconds = %s WHERE id = %s", (checked, job_id))
            _write(plan, archive, user_id, progress=lambda n, total: _progress(job_id, "replacing", n, total), job=(job_id, summary, len(plan["files"])))
            log.info("restore %s: checked in %.1fs, replaced in %.1fs (%s print files)", job_id, checked, time.monotonic() - began - checked, len(plan["files"]))
            try:
                stock_changed()
            except Exception:
                log.exception("low-stock check after a restore failed")
        except Exception as exc:
            known = isinstance(exc, (ApiError, Localized))
            if not known:
                log.exception("restore %s failed", job_id)
            reason = render(exc.msg if known else L("backup.err_unexpected"), lang)
            try:
                with pool().connection() as conn:
                    conn.execute("UPDATE backup_jobs SET status = 'failed', error_key = 'backup.failed', error_params = %s::jsonb, finished_at = now(), "
                                 "updated_at = now() WHERE id = %s", (json.dumps({"reason": reason}), job_id))
            except Exception:
                log.exception("could not mark restore %s as failed", job_id)
        finally:
            if archive:
                archive.close()
            staged.unlink(missing_ok=True)


def _write(plan: dict, archive, user_id, progress=None, job=None) -> None:
    """Swap the plan in, all or nothing. `job` = (id, summary, steps): the job is marked done in the same transaction as the swap."""
    upload_dir = Path(config().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    written, old_files = [], []
    started = time.monotonic()
    try:
        with pool().connection() as conn:
            conn.execute("DELETE FROM projects")
            conn.execute("DELETE FROM orders")
            conn.execute("DELETE FROM customers")
            conn.execute("DELETE FROM invoice_counters")
            for table in ("invoice_template", "invoice_logo"):
                replaced = conn.execute(f"DELETE FROM {table} RETURNING stored_name").fetchone()
                if replaced and replaced["stored_name"]:                       # a file an earlier release left under UPLOAD_DIR
                    old_files.append(replaced["stored_name"])
            for table in ("filament_spools", "filament_library", "packaging_items", "part_items", "accessory_items", "energy_tariffs", "printers"):
                conn.execute(f"DELETE FROM {table}")
            if plan["files"]:
                old_files += [r["stored_name"] for r in conn.execute("DELETE FROM print_files RETURNING stored_name").fetchall()]
                for n, item in enumerate(plan["files"], 1):
                    if progress:
                        progress(n, len(plan["files"]))
                    stored = f"{uuid.uuid4().hex}.{item['kind']}"
                    (upload_dir / stored).write_bytes(item["content"] if item["member"] is None else _read_member(archive, item["member"], item["size"]))
                    written.append(upload_dir / stored)
                    _insert(conn, "print_files", {"id": item["id"], "filename": item["filename"], "kind": item["kind"],
                                                  "size_bytes": item["size"], "sha256": item["sha256"],
                                                  "stored_name": stored, "analysis": json.dumps(item["analysis"]),
                                                  **({"created_at": item["created_at"]} if item["created_at"] else {})})
            for _key, (table, items) in plan["sections"].items():
                for item in items:
                    values = {"id": item["id"], **item["values"]}
                    if item["created_at"]:
                        values["created_at"] = item["created_at"]
                    _insert(conn, table, values)
            existing_files = {str(r["id"]) for r in conn.execute("SELECT id FROM print_files").fetchall()}
            for item in plan["projects"]:
                f = item["fields"]
                file_id = f["file_id"] if f["file_id"] in existing_files else None     # a file that is not here is let go
                values = {"id": item["id"], "number": item["number"], "name": f["name"], "notes": f["notes"], "object_description": f["object_description"],
                          "margin_pct": f["margin_pct"],
                          "vat_pct": f["vat_pct"], "price_rounding": f["price_rounding"], "data": json.dumps(f["data"]),
                          "totals": json.dumps(f["totals"]), "source_url": f["source_url"], "file_id": file_id,
                          "stock_booked_at": item["stock_booked_at"]}
                if item["created_at"]:
                    values["created_at"] = item["created_at"]
                    values["updated_at"] = item["updated_at"] or item["created_at"]
                _insert(conn, "projects", values)
            for img in plan["project_images"]:
                conn.execute("INSERT INTO project_images (project_id, kind, variant, mime, content, width_px, height_px, is_cover"
                             + (", created_at" if img["created_at"] else "") + ") VALUES (%s, %s, %s, 'image/jpeg', %s, %s, %s, %s"
                             + (", %s" if img["created_at"] else "") + ")",
                             (img["project_id"], img["kind"], img["variant"], img["content"], img["width"], img["height"], img["is_cover"],
                              *([img["created_at"]] if img["created_at"] else [])))
            if plan["ai_settings"]:                                 # model and quality only; the API key stays where it is
                conn.execute("INSERT INTO ai_image_settings (id, model, quality) VALUES (true, %s, %s) "
                             "ON CONFLICT (id) DO UPDATE SET model = EXCLUDED.model, quality = EXCLUDED.quality, updated_at = now()",
                             (plan["ai_settings"]["model"], plan["ai_settings"]["quality"]))
            conn.execute(f"ALTER SEQUENCE project_number_seq RESTART WITH {max((p['number'] for p in plan['projects']), default=0) + 1}")
            for c in plan["customers"]:
                _insert(conn, "customers", {"id": c["id"], **c["values"], **({"created_at": c["created_at"]} if c["created_at"] else {}),
                                            **({"updated_at": c["updated_at"]} if c["updated_at"] else {})})
            _restore_orders(conn, plan["orders"])
            for pdf in plan["invoice_pdfs"]:
                conn.execute("INSERT INTO invoice_pdfs (order_id, invoice_number, content, size_bytes) VALUES (%s, %s, %s, %s)",
                             (pdf["order_id"], pdf["invoice_number"], pdf["content"], len(pdf["content"])))
            if plan["template"]:
                t = plan["template"]
                invoice_template.replace(conn, filename=t["filename"], kind=t["kind"], content=t["content"], top=t["top"], bottom=t["bottom"])
            if plan["logo"]:
                lg = plan["logo"]
                invoice_logo.replace(conn, filename=lg["filename"], kind=lg["kind"], content=lg["content"], width=lg["width"], height=lg["height"])
            conn.execute("UPDATE users SET preferences = %s::jsonb WHERE id = %s", (json.dumps(plan["preferences"]), user_id))
            if job:
                conn.execute("UPDATE backup_jobs SET status = 'done', phase = 'done', step = %s, steps = %s, summary = %s::jsonb, replacing_seconds = %s, "
                             "finished_at = now(), updated_at = now() WHERE id = %s", (job[2], job[2], json.dumps(job[1]), round(time.monotonic() - started, 1), job[0]))
    except Exception:
        for path in written:                                          # nothing was swapped in: take the new files out again
            path.unlink(missing_ok=True)
        raise
    for name in old_files:                                            # swapped in: the replaced files can go
        (upload_dir / name).unlink(missing_ok=True)
