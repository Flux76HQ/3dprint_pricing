"""Backup and restore of everything the owner has entered: settings, printers, electricity tariffs, packaging,
filament rolls and calculations (optionally the uploaded print files too).

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
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, g, jsonify, request

from . import invoice_docs, invoice_logo, invoice_template, orders, printfile
from .api import RESOURCES, _project_fields, _serialise, _validated, stock_changed, validated_preferences
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, Localized

bp = Blueprint("backup", __name__, url_prefix="/api/backup")

FORMAT = "printpricing-backup"
FORMAT_VERSION = 2          # 2: orders, the invoice template and calculation numbers; a file of version 1 still restores
MAX_ROWS = 20_000
# (key in the file, key in api.RESOURCES) -- the order is the order of insertion
SECTIONS = (("printers", "printers"), ("tariffs", "tariffs"), ("packaging", "packaging"), ("spools", "spools"))
PROJECT_COLUMNS = ("id", "number", "name", "notes", "margin_pct", "vat_pct", "price_rounding", "data", "totals", "source_url",
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
        doc["orders"] = _export_orders(conn)
        doc["invoice_pdfs"] = [{"order_id": str(r["order_id"]), "invoice_number": r["invoice_number"],
                                "content_b64": base64.b64encode(bytes(r["content"])).decode("ascii")}
                               for r in conn.execute("SELECT order_id, invoice_number, content FROM invoice_pdfs ORDER BY created_at, order_id").fetchall()]
        try:
            template = invoice_template.load(conn)
        except ApiError:                                             # the file went missing: the rest of the backup is still worth having
            template = None
        logo = invoice_logo.load(conn)
        if logo:
            doc["invoice_logo"] = {"filename": logo["filename"], "kind": logo["kind"], "content_b64": base64.b64encode(logo["content"]).decode("ascii")}
        if template:
            doc["invoice_template"] = {"filename": template["filename"], "kind": template["kind"], "margin_top_mm": template["margin_top_mm"],
                                       "margin_bottom_mm": template["margin_bottom_mm"],
                                       "content_b64": base64.b64encode(template["content"]).decode("ascii")}
        if include_files:
            files = []
            for row in conn.execute("SELECT * FROM print_files ORDER BY created_at, id").fetchall():
                path = Path(config().upload_dir) / row["stored_name"]
                if not path.is_file():
                    continue                                         # the row outlived its file: nothing to back up
                files.append({"id": str(row["id"]), "filename": row["filename"], "kind": row["kind"],
                              "sha256": row["sha256"], "created_at": row["created_at"].isoformat(),
                              "content_b64": base64.b64encode(path.read_bytes()).decode("ascii")})
            doc["files"] = files
    name = f"printpricing-backup-{datetime.now().strftime('%Y-%m-%d')}.json"
    return Response(json.dumps(doc, ensure_ascii=False), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


MAX_INVOICE_PDF_BYTES = 10 * 1024 * 1024
ORDER_COLUMNS = ("id", "number", "invoice_number", "invoice_date", "created_at", "updated_at", *orders.ORDER_FIELDS)


def _export_orders(conn) -> list:
    out = []
    rows = conn.execute(f"SELECT {', '.join(ORDER_COLUMNS)} FROM orders ORDER BY number").fetchall()
    lines = orders._lines_of(conn, [r["id"] for r in rows])
    for row in rows:
        item = _serialise(row)
        item["lines"] = [_serialise({k: line[k] for k in ("project_id", "project_number", "description", "quantity", "unit_price", "vat_pct")})
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


def _parse(doc) -> dict:
    """Check the whole file and turn it into what will be written. Nothing is written here."""
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
        for n, entry in enumerate(_rows(doc, "files"), 1):
            try:
                plan["files"].append(_parse_file(entry))
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
    plan["orders"] = _parse_orders(doc)
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
                           "invoice_date": values["invoice_date"] if invoice else None, "created_at": _when(row.get("created_at")),
                           "updated_at": _when(row.get("updated_at"))})
        except (ApiError, Localized) as exc:
            raise _row_error("orders", n, exc) from None
    return parsed


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


def _parse_file(entry) -> dict:
    if not isinstance(entry, dict):
        raise Localized("backup.bad_row_type")
    kind = entry.get("kind")
    if kind not in ("stl", "3mf"):
        raise Localized("pf.unsupported")
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
            "content": content, "sha256": digest, "analysis": analysis, "created_at": _when(entry.get("created_at"))}


def _summary(plan: dict) -> dict:
    return {"printers": len(plan["sections"]["printers"][1]), "tariffs": len(plan["sections"]["tariffs"][1]),
            "packaging": len(plan["sections"]["packaging"][1]), "spools": len(plan["sections"]["spools"][1]),
            "projects": len(plan["projects"]), "files": len(plan["files"]), "preferences": len(plan["preferences"]),
            "orders": len(plan["orders"]), "template": 1 if plan["template"] else 0, "logo": 1 if plan["logo"] else 0}


def _insert(conn, table: str, values: dict) -> None:
    columns = list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
                 tuple(values.values()))


def _restore_orders(conn, items: list) -> None:
    for item in items:
        v = item["values"]
        columns = {"id": item["id"], "number": item["number"], "invoice_number": item["invoice_number"], "invoice_date": item["invoice_date"],
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


@bp.post("/restore")
def restore():
    body = json_body()
    dry_run = request.args.get("dry_run") == "1"
    plan = _parse(body)
    summary = {**_summary(plan), "app_version": str(body.get("app_version", ""))[:40],
               "created_at": str(body.get("created_at", ""))[:40], "includes_files": bool(plan["files"])}
    if dry_run:
        return jsonify({"ok": True, "dry_run": True, "summary": summary})

    upload_dir = Path(config().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    written, old_files = [], []
    try:
        with pool().connection() as conn:
            conn.execute("DELETE FROM projects")
            conn.execute("DELETE FROM orders")
            conn.execute("DELETE FROM invoice_counters")
            for table in ("invoice_template", "invoice_logo"):
                replaced = conn.execute(f"DELETE FROM {table} RETURNING stored_name").fetchone()
                if replaced and replaced["stored_name"]:                       # a file an earlier release left under UPLOAD_DIR
                    old_files.append(replaced["stored_name"])
            for table in ("filament_spools", "packaging_items", "energy_tariffs", "printers"):
                conn.execute(f"DELETE FROM {table}")
            if plan["files"]:
                old_files += [r["stored_name"] for r in conn.execute("DELETE FROM print_files RETURNING stored_name").fetchall()]
                for item in plan["files"]:
                    stored = f"{uuid.uuid4().hex}.{item['kind']}"
                    (upload_dir / stored).write_bytes(item["content"])
                    written.append(upload_dir / stored)
                    _insert(conn, "print_files", {"id": item["id"], "filename": item["filename"], "kind": item["kind"],
                                                  "size_bytes": len(item["content"]), "sha256": item["sha256"],
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
                values = {"id": item["id"], "number": item["number"], "name": f["name"], "notes": f["notes"], "margin_pct": f["margin_pct"],
                          "vat_pct": f["vat_pct"], "price_rounding": f["price_rounding"], "data": json.dumps(f["data"]),
                          "totals": json.dumps(f["totals"]), "source_url": f["source_url"], "file_id": file_id,
                          "stock_booked_at": item["stock_booked_at"]}
                if item["created_at"]:
                    values["created_at"] = item["created_at"]
                    values["updated_at"] = item["updated_at"] or item["created_at"]
                _insert(conn, "projects", values)
            conn.execute(f"ALTER SEQUENCE project_number_seq RESTART WITH {max((p['number'] for p in plan['projects']), default=0) + 1}")
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
            conn.execute("UPDATE users SET preferences = %s::jsonb WHERE id = %s", (json.dumps(plan["preferences"]), g.user_id))
    except Exception:
        for path in written:                                          # nothing was swapped in: take the new files out again
            path.unlink(missing_ok=True)
        raise
    for name in old_files:                                            # swapped in: the replaced files can go
        (upload_dir / name).unlink(missing_ok=True)
    stock_changed()                                                   # the restored shelf and thresholds may already be low
    return jsonify({"ok": True, "dry_run": False, "summary": summary})
