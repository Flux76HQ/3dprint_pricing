"""Customers: who an order is for. A customer has a number (the klantnummer on the invoice), contact details and a note.

An order points at its customer and keeps a copy of the details (see migration 0014): saving the order copies them again, and
editing a customer updates the copy in its orders that have no invoice yet, so an invoice that went out is never rewritten.
"""
from flask import Blueprint, jsonify, request

from .api import _serialise, text
from .db import UniqueViolation
from .http import ApiError, json_body, login_required, pool

bp = Blueprint("customers", __name__, url_prefix="/api/customers")

TEXT_FIELDS = (("name", "f.customer_name", 120, True), ("address", "f.address", 200, False), ("postal_code", "f.postal_code", 20, False),
               ("city", "f.city", 100, False), ("country", "f.country", 60, False), ("email", "f.email", 200, False),
               ("phone", "f.phone", 40, False), ("notes", "f.notes", 2000, False))
FIELDS = ("number", *(f[0] for f in TEXT_FIELDS))


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def validated_customer(body: dict) -> dict:
    """The customer in `body` as it will be stored (an empty number means: give the next free one)."""
    values = {key: text(label, required=required, max_len=limit)(body.get(key)) for key, label, limit, required in TEXT_FIELDS}
    if values["email"] and "@" not in values["email"]:
        raise ApiError(400, "err.bad_email")
    values["number"] = text("f.customer_number", required=False, max_len=40)(body.get("number"))
    return values


def next_number(conn) -> str:
    """The next free whole number (one more than the highest whole number in use)."""
    row = conn.execute("SELECT COALESCE(MAX(CAST(number AS INTEGER)), 0) + 1 AS n FROM customers "
                       "WHERE number NOT GLOB '*[^0-9]*' AND length(number) BETWEEN 1 AND 9").fetchone()
    return str(row["n"])


def snapshot(customer) -> dict:
    """What an order copies from its customer."""
    return {"customer_name": customer["name"], "customer_number": customer["number"], "address": customer["address"],
            "postal_code": customer["postal_code"], "city": customer["city"], "country": customer["country"],
            "email": customer["email"], "phone": customer["phone"]}


def insert(conn, values: dict, **extra):
    number = values["number"] or next_number(conn)
    columns = {**values, "number": number, **extra}
    try:
        return conn.execute(f"INSERT INTO customers ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING *",
                            tuple(columns.values())).fetchone()
    except UniqueViolation:
        raise ApiError(409, "err.customer_number_taken", number=number) from None


def _present(row, orders_count: int = 0) -> dict:
    out = _serialise(row)
    out["orders"] = orders_count
    return out


@bp.get("")
def list_customers():
    query = (request.args.get("q") or "").strip()
    sql = ("SELECT c.*, (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) AS orders_count FROM customers c")
    params = []
    if query:
        like = f"%{query.replace('%', '').replace('_', '')}%"
        sql += " WHERE c.name ILIKE %s OR c.number ILIKE %s OR c.city ILIKE %s OR c.email ILIKE %s"
        params = [like] * 4
    sql += " ORDER BY lower(c.name), c.number LIMIT 500"
    with pool().connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return jsonify([_present({k: v for k, v in r.items() if k != "orders_count"}, r["orders_count"]) for r in rows])


@bp.get("/<uuid:customer_id>")
def get_customer(customer_id):
    with pool().connection() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
        count = conn.execute("SELECT count(*) AS n FROM orders WHERE customer_id = %s", (customer_id,)).fetchone()["n"] if row else 0
    if row is None:
        raise ApiError(404, "err.customer_not_found")
    return jsonify(_present(row, count))


@bp.post("")
def create_customer():
    values = validated_customer(json_body())
    with pool().connection() as conn:
        row = insert(conn, values)
    return jsonify(_present(row)), 201


@bp.put("/<uuid:customer_id>")
def update_customer(customer_id):
    values = validated_customer(json_body())
    with pool().connection() as conn:
        current = conn.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
        if current is None:
            raise ApiError(404, "err.customer_not_found")
        number = values["number"] or current["number"]                      # leaving the number empty keeps it
        values = {**values, "number": number}
        sets = ", ".join(f"{f} = %s" for f in FIELDS)
        try:
            row = conn.execute(f"UPDATE customers SET {sets}, updated_at = now() WHERE id = %s RETURNING *",
                               (*[values[f] for f in FIELDS], customer_id)).fetchone()
        except UniqueViolation:
            raise ApiError(409, "err.customer_number_taken", number=number) from None
        copy = snapshot(row)
        conn.execute("UPDATE orders SET " + ", ".join(f"{f} = %s" for f in copy) + ", updated_at = now() "
                     "WHERE customer_id = %s AND invoice_number IS NULL", (*copy.values(), customer_id))
        count = conn.execute("SELECT count(*) AS n FROM orders WHERE customer_id = %s", (customer_id,)).fetchone()["n"]
    return jsonify(_present(row, count))


@bp.delete("/<uuid:customer_id>")
def delete_customer(customer_id):
    with pool().connection() as conn:
        count = conn.execute("SELECT count(*) AS n FROM orders WHERE customer_id = %s", (customer_id,)).fetchone()["n"]
        if count:
            raise ApiError(409, "err.customer_in_use", n=count)
        row = conn.execute("DELETE FROM customers WHERE id = %s RETURNING id", (customer_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.customer_not_found")
    return jsonify({"ok": True})
