"""The API for other applications: `/api/v1`, read-only, with an API key (`api_keys.py`).

What a bookkeeping or finance application needs and nothing more: orders with their lines and totals, the invoice (its number, its date
and the PDF) and customers. **Cost prices and margins are not in it**: an order line says what the customer pays, not what it cost. Notes
that are for the business itself are left out too.

The screens' own API (`/api/orders`, ...) is not this one and makes no promise to anyone else: it changes with the screens. This one
is versioned in its path. Adding a field is not a new version; removing or renaming one is, and then `/api/v1` stays for as long as
something still uses it.

A session cookie is not accepted here and a key is accepted nowhere else, so neither can stand in for the other. Lists are paged with a
cursor (`next_cursor`), oldest change first, so a client that keeps the last cursor reads only what changed since."""
import base64
import binascii
import uuid
from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify, request

from . import api_keys
from .api import _serialise
from .db import id_list
from .http import ApiError, pool
from .orders import STATUSES, _lines_of, _pdf_response, compute_totals

bp = Blueprint("public_api", __name__, url_prefix="/api/v1")
PAGE, MAX_PAGE = 100, 200


@bp.before_request
def _guard():
    """Every route here takes an API key, and only that."""
    g.api_key = api_keys.authenticate()


def _page_size() -> int:
    raw = request.args.get("limit", "")
    if not raw:
        return PAGE
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_PAGE:
        raise ApiError(400, "v1.err_limit", max=MAX_PAGE)
    return int(raw)


def _moment(name: str):
    """A moment given in the address (`updated_since=2026-11-11T08:00:00Z`), or None when it is not there."""
    raw = request.args.get(name, "")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(400, "v1.err_moment", name=name) from None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _cursor():
    """Where the previous page ended: the moment of change and the id of its last row, as the opaque text that page gave."""
    raw = request.args.get("cursor", "")
    if not raw:
        return None
    try:
        moment, _, ident = base64.urlsafe_b64decode(raw.encode("ascii") + b"==").decode("ascii").partition("|")
        return datetime.fromisoformat(moment), uuid.UUID(ident)
    except (ValueError, binascii.Error, UnicodeError):
        raise ApiError(400, "v1.err_cursor") from None


def _next(rows: list, size: int):
    if len(rows) <= size:
        return None
    last = rows[size - 1]
    return base64.urlsafe_b64encode(f"{last['updated_at'].isoformat()}|{last['id']}".encode("ascii")).decode("ascii").rstrip("=")


def _paged(conn, table: str, where: list, params: list, size: int) -> list:
    """One page of `table`, in the order of the last change (the id decides between equal moments), plus one row to know whether there is more."""
    since, after = _moment("updated_since"), _cursor()
    if since is not None:
        where.append("updated_at >= %s")
        params.append(since)
    if after is not None:
        where.append("(updated_at > %s OR (updated_at = %s AND id > %s))")
        params += [after[0], after[0], after[1]]
    sql = f"SELECT * FROM {table}" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated_at, id LIMIT %s"
    return conn.execute(sql, (*params, size + 1)).fetchall()


def order_view(order: dict, lines: list, has_pdf: bool) -> dict:
    """An order as another application sees it: what is on the invoice, never what it cost."""
    totals = compute_totals(lines)
    out = _serialise({k: order[k] for k in ("id", "number", "status", "order_date", "delivery_date", "subject", "created_at", "updated_at")})
    out["customer"] = _serialise({"id": order["customer_id"], "number": order["customer_number"], "name": order["customer_name"],
                                  **{k: order[k] for k in ("address", "postal_code", "city", "country", "email", "phone")}})
    out["invoice"] = {"number": order["invoice_number"], "date": order["invoice_date"].isoformat(), "has_pdf": has_pdf} if order["invoice_number"] else None
    out["lines"] = [{**_serialise({k: line[k] for k in ("position", "description", "quantity", "unit_price", "vat_pct", "optional")}),
                     "total": totals["line_totals"][i], "net": totals["line_net"][i], "vat": totals["line_vat"][i]} for i, line in enumerate(lines)]
    out["totals"] = {"excl": totals["total_excl"], "vat": totals["total_vat"], "incl": totals["total"], "by_vat_rate": totals["vat"]}
    return out


def customer_view(row: dict) -> dict:
    return _serialise({k: row[k] for k in ("id", "number", "name", "address", "postal_code", "city", "country", "email", "phone", "created_at", "updated_at")})


@bp.get("")
def about():
    """Whether the key works, and what answers."""
    from . import VERSION                                             # the package imports this module, so not at the top
    return jsonify({"name": "3D Print Pricing", "api": 1, "version": VERSION, "key": g.api_key["name"]})


@bp.get("/orders")
def list_orders():
    size, where, params = _page_size(), [], []
    status = request.args.get("status", "")
    if status:
        if status not in STATUSES:
            raise ApiError(400, "err.order_status")
        where.append("status = %s")
        params.append(status)
    invoiced = request.args.get("invoiced", "")
    if invoiced:
        if invoiced not in ("true", "false"):
            raise ApiError(400, "v1.err_invoiced")
        where.append("invoice_number IS NOT NULL" if invoiced == "true" else "invoice_number IS NULL")
    with pool().read() as conn:
        rows = _paged(conn, "orders", where, params, size)
        page = rows[:size]
        ids = [o["id"] for o in page]
        lines = _lines_of(conn, ids)
        with_pdf = {r["order_id"] for r in conn.execute("SELECT order_id FROM invoice_pdfs WHERE order_id IN (SELECT value FROM json_each(%s))", (id_list(ids),)).fetchall()} if ids else set()
    return jsonify({"data": [order_view(o, lines[o["id"]], o["id"] in with_pdf) for o in page], "next_cursor": _next(rows, size)})


@bp.get("/orders/<uuid:order_id>")
def get_order(order_id):
    with pool().read() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id = %s", (order_id,)).fetchone()
        if order is None:
            raise ApiError(404, "err.order_not_found")
        lines = _lines_of(conn, [order_id])[order_id]
        has_pdf = conn.execute("SELECT 1 FROM invoice_pdfs WHERE order_id = %s", (order_id,)).fetchone() is not None
    return jsonify(order_view(order, lines, has_pdf))


@bp.get("/orders/<uuid:order_id>/invoice")
def get_invoice(order_id):
    """The invoice as it was made, as a PDF. Making one is done in the app, not here."""
    with pool().read() as conn:
        row = conn.execute("SELECT invoice_number, content FROM invoice_pdfs WHERE order_id = %s", (order_id,)).fetchone()
    if row is None:
        raise ApiError(404, "invoice.err_no_pdf")
    return _pdf_response(row["invoice_number"], bytes(row["content"]))


def item_view(listing: dict, project: dict, photos: list) -> dict:
    """What a model is offered for sale as (`listings.py`): what a sales channel needs, never what it costs to make."""
    out = _serialise({"id": project["id"], "number": project["number"], "title": listing["title"], "description": listing["description"],
                      "price": listing["price"], "vat_pct": project["vat_pct"], "ean": listing["ean"] or None, "updated_at": listing["updated_at"]})
    out["photos"] = [{"id": str(p["id"]), "width": p["width_px"], "height": p["height_px"], "url": f"/api/v1/items/{project['id']}/photos/{p['id']}"} for p in photos]
    out["links"] = [{"kind": link["kind"], "label": link["label"], "url": link["url"]} for link in project["links"]]       # where it is offered already
    return out


def _items(conn, listings_rows: list) -> list:
    ids = [row["project_id"] for row in listings_rows]
    if not ids:
        return []
    projects = {p["id"]: p for p in conn.execute("SELECT id, number, vat_pct, links FROM projects WHERE id IN (SELECT value FROM json_each(%s))", (id_list(ids),)).fetchall()}
    photos: dict = {pid: [] for pid in ids}
    for photo in conn.execute("SELECT id, project_id, width_px, height_px FROM listing_photos WHERE project_id IN (SELECT value FROM json_each(%s)) "
                              "ORDER BY project_id, position, created_at, id", (id_list(ids),)).fetchall():
        photos[photo["project_id"]].append(photo)
    return [item_view(row, projects[row["project_id"]], photos[row["project_id"]]) for row in listings_rows]


@bp.get("/items")
def list_items():
    """The models that are for sale, oldest change of the listing first. An item's `id` is that of its 3D model."""
    size = _page_size()
    with pool().read() as conn:
        rows = _paged(conn, "listings", [], [], size)
        data = _items(conn, rows[:size])
    return jsonify({"data": data, "next_cursor": _next(rows, size)})


@bp.get("/items/<uuid:project_id>")
def get_item(project_id):
    with pool().read() as conn:
        row = conn.execute("SELECT * FROM listings WHERE project_id = %s", (project_id,)).fetchone()
        if row is None:
            raise ApiError(404, "err.not_found")
        return jsonify(_items(conn, [row])[0])


@bp.get("/items/<uuid:project_id>/photos/<uuid:photo_id>")
def get_item_photo(project_id, photo_id):
    with pool().read() as conn:
        row = conn.execute("SELECT content FROM listing_photos WHERE id = %s AND project_id = %s AND EXISTS (SELECT 1 FROM listings l WHERE l.project_id = %s)",
                           (photo_id, project_id, project_id)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return Response(bytes(row["content"]), mimetype="image/jpeg")


@bp.get("/customers")
def list_customers():
    size = _page_size()
    with pool().read() as conn:
        rows = _paged(conn, "customers", [], [], size)
    return jsonify({"data": [customer_view(r) for r in rows[:size]], "next_cursor": _next(rows, size)})


@bp.get("/customers/<uuid:customer_id>")
def get_customer(customer_id):
    with pool().read() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.not_found")
    return jsonify(customer_view(row))
