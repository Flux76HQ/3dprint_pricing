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

from . import printfile
from .api import RESOURCES, _project_fields, _serialise, _validated, stock_changed, validated_preferences
from .http import ApiError, config, json_body, login_required, pool
from .i18n import L, Localized

bp = Blueprint("backup", __name__, url_prefix="/api/backup")

FORMAT = "printpricing-backup"
FORMAT_VERSION = 1
MAX_ROWS = 20_000
# (key in the file, key in api.RESOURCES) -- the order is the order of insertion
SECTIONS = (("printers", "printers"), ("tariffs", "tariffs"), ("packaging", "packaging"), ("spools", "spools"))
PROJECT_COLUMNS = ("id", "name", "notes", "margin_pct", "vat_pct", "price_rounding", "data", "totals", "source_url",
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
    plan["projects"] = projects
    return plan


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
            "projects": len(plan["projects"]), "files": len(plan["files"]), "preferences": len(plan["preferences"])}


def _insert(conn, table: str, values: dict) -> None:
    columns = list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
                 tuple(values.values()))


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
            for table in ("filament_spools", "packaging_items", "energy_tariffs", "printers"):
                conn.execute(f"DELETE FROM {table}")
            if plan["files"]:
                old_files = [r["stored_name"] for r in conn.execute("DELETE FROM print_files RETURNING stored_name").fetchall()]
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
                values = {"id": item["id"], "name": f["name"], "notes": f["notes"], "margin_pct": f["margin_pct"],
                          "vat_pct": f["vat_pct"], "price_rounding": f["price_rounding"], "data": json.dumps(f["data"]),
                          "totals": json.dumps(f["totals"]), "source_url": f["source_url"], "file_id": file_id,
                          "stock_booked_at": item["stock_booked_at"]}
                if item["created_at"]:
                    values["created_at"] = item["created_at"]
                    values["updated_at"] = item["updated_at"] or item["created_at"]
                _insert(conn, "projects", values)
            conn.execute("UPDATE users SET preferences = %s::jsonb WHERE id = %s", (json.dumps(plan["preferences"]), g.user_id))
    except Exception:
        for path in written:                                          # nothing was swapped in: take the new files out again
            path.unlink(missing_ok=True)
        raise
    for name in old_files:                                            # swapped in: the replaced files can go
        (upload_dir / name).unlink(missing_ok=True)
    stock_changed()                                                   # the restored shelf and thresholds may already be low
    return jsonify({"ok": True, "dry_run": False, "summary": summary})
