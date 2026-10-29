"""Orders: a customer's order of several prints, and the invoice made from it.

The prices on an order line are the price per piece including VAT, copied from a calculation when the line is made (or typed for
a line of its own); the totals are worked out here, never in the browser: per VAT rate the VAT is taken out of the sum of the
lines, so what the customer pays is exactly the sum of what the lines say.
"""
import re
import uuid
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from flask import Blueprint, Response, g, jsonify, request

from . import calc, customers, invoice_docs, invoice_logo, invoice_numbers, invoice_template, preferences
from .api import _serialise, boolean, number, text
from .db import id_list, next_number
from .http import ApiError, json_body, login_required, pool
from .i18n import L

bp = Blueprint("orders", __name__, url_prefix="/api/orders")

STATUSES = ("nieuw", "verwerkt", "verstuurd", "afgehandeld")
MAX_LINES = 200
CENT = Decimal("0.01")


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


# --- totals -----------------------------------------------------------------------------------------------------

def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _split_net(grosses: list, rate: Decimal) -> list:
    """The net part of each gross amount of one VAT rate, in cents, so that the nets add up to exactly the net of the whole
    (the VAT is taken out of the sum): every line gets its rounded-down share and the cents that are left go to the lines with the
    largest remainders."""
    total = sum(grosses, Decimal(0))
    group_net = total - (_money(total - total / (1 + rate / 100)) if rate > 0 else Decimal(0))
    if rate <= 0:
        return list(grosses)
    exact = [g / (1 + rate / 100) for g in grosses]
    nets = [e.quantize(CENT, rounding=ROUND_DOWN) for e in exact]
    left = int(((group_net - sum(nets, Decimal(0))) / CENT).to_integral_value())
    order = sorted(range(len(nets)), key=lambda i: (exact[i] - nets[i], -i), reverse=True)
    for i in order[:max(left, 0)]:
        nets[i] += CENT
    return nets


def compute_totals(lines: list) -> dict:
    """The line totals and, per VAT rate, what is net, what is VAT and what is gross; also the net and VAT part of every line.
    Amounts are strings with two decimals."""
    gross_by_rate: dict[Decimal, list] = {}
    line_totals, rates = [], []
    for index, line in enumerate(lines):
        total = _money(Decimal(line["quantity"]) * Decimal(line["unit_price"]))
        line_totals.append(total)
        rate = Decimal(line["vat_pct"]).quantize(CENT)
        rates.append(rate)
        gross_by_rate.setdefault(rate, []).append(index)
    vat_rows, net_sum, vat_sum, gross_sum = [], Decimal(0), Decimal(0), Decimal(0)
    line_net = [Decimal(0)] * len(lines)
    for rate in sorted(gross_by_rate):
        indexes = gross_by_rate[rate]
        grosses = [line_totals[i] for i in indexes]
        gross = sum(grosses, Decimal(0))
        vat = _money(gross - gross / (1 + rate / 100)) if rate > 0 else _money(Decimal(0))
        for i, net in zip(indexes, _split_net(grosses, rate)):
            line_net[i] = net
        vat_rows.append({"pct": format(rate.normalize(), "f"), "net": str(gross - vat), "vat": str(vat), "gross": str(gross)})
        net_sum, vat_sum, gross_sum = net_sum + gross - vat, vat_sum + vat, gross_sum + gross
    return {"line_totals": [str(t) for t in line_totals], "line_net": [str(n) for n in line_net],
            "line_vat": [str(t - n) for t, n in zip(line_totals, line_net)], "vat": vat_rows,
            "total_excl": str(_money(net_sum)), "total_vat": str(_money(vat_sum)), "total": str(_money(gross_sum))}


# --- validation (also used by restoring a backup) -----------------------------------------------------------------

def _date(label: str, value, *, required: bool):
    if value in (None, ""):
        if required:
            raise ApiError(400, "err.required", label=L(label))
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ApiError(400, "err.bad_date", label=L(label)) from None


def _line(raw, n: int, rounding: str = "none") -> dict:
    """One order line. With a `cost_price` the price per piece is worked out here from the cost price, the line's own margin, the VAT
    and the order's rounding; without one the typed `unit_price` is kept."""
    if not isinstance(raw, dict):
        raise ApiError(400, "err.order_line", n=n)
    try:
        quantity = Decimal(str(raw.get("quantity")))
    except ArithmeticError:
        raise ApiError(400, "err.order_quantity", n=n) from None
    if not quantity.is_finite() or quantity != quantity.to_integral_value() or not 1 <= quantity <= 100_000:
        raise ApiError(400, "err.order_quantity", n=n)
    project_id = raw.get("project_id") or None
    if project_id is not None:
        try:
            project_id = uuid.UUID(str(project_id))
        except ValueError:
            raise ApiError(400, "err.order_line", n=n) from None
    vat_pct = _money(number("f.vat", maximum=100)(raw.get("vat_pct", 0)))
    cost_price = margin_pct = effective = None
    if raw.get("cost_price") not in (None, ""):
        cost_price = _money(number("f.cost_price")(raw["cost_price"]))
        margin_pct = _money(number("f.margin", maximum=1000)(raw.get("margin_pct") or 0))
        price = calc.price_from_cost(cost_price, margin_pct, vat_pct, rounding)
        unit_price, effective = price["sell_price_incl_vat"], str(price["margin_pct_effective"])
    else:
        unit_price = _money(number("f.unit_price")(raw.get("unit_price")))
    optional = boolean("f.optional")(raw["optional"]) if "optional" in raw else False
    return {"project_id": project_id, "project_number": None, "optional": optional, "description": text("f.description", max_len=200)(raw.get("description")),
            "quantity": int(quantity), "unit_price": unit_price, "vat_pct": vat_pct, "cost_price": cost_price, "margin_pct": margin_pct,
            "margin_pct_effective": effective}


def _rounding(value) -> str:
    value = value or "none"
    if value not in calc.ROUNDINGS:
        raise ApiError(400, "err.rounding")
    return value


def validated_order(body: dict) -> dict:
    """The order in `body` as it will be stored; raises ApiError for a bad value."""
    status = body.get("status", "nieuw")
    if status not in STATUSES:
        raise ApiError(400, "err.order_status")
    email = text("f.email", required=False, max_len=200)(body.get("email"))
    if email and "@" not in email:
        raise ApiError(400, "err.bad_email")
    raw_lines = body.get("lines", [])
    if not isinstance(raw_lines, list) or len(raw_lines) > MAX_LINES:
        raise ApiError(400, "err.order_lines", max=MAX_LINES)
    rounding = _rounding(body.get("price_rounding"))
    return {
        "status": status,
        "price_rounding": rounding,
        "order_date": _date("f.order_date", body.get("order_date") or date.today().isoformat(), required=True),
        "delivery_date": _date("f.delivery_date", body.get("delivery_date"), required=False),
        "customer_name": text("f.customer_name")(body.get("customer_name")),
        "customer_number": text("f.customer_number", required=False, max_len=40)(body.get("customer_number")),
        "subject": text("f.subject", required=False, max_len=200)(body.get("subject")),
        "address": text("f.address", required=False, max_len=200)(body.get("address")),
        "postal_code": text("f.postal_code", required=False, max_len=20)(body.get("postal_code")),
        "city": text("f.city", required=False, max_len=100)(body.get("city")),
        "country": text("f.country", required=False, max_len=60)(body.get("country")),
        "email": email,
        "phone": text("f.phone", required=False, max_len=40)(body.get("phone")),
        "notes": text("f.notes", required=False, max_len=2000)(body.get("notes")),
        "invoice_date": _date("f.invoice_date", body.get("invoice_date"), required=False),
        "lines": [_line(raw, n, rounding) for n, raw in enumerate(raw_lines, 1)],
    }


# --- storage ----------------------------------------------------------------------------------------------------

ORDER_FIELDS = ("price_rounding", "status", "order_date", "delivery_date", "customer_name", "customer_number", "subject", "address", "postal_code", "city",
                "country", "email", "phone", "notes")


def _write_lines(conn, order_id, lines: list) -> None:
    known = {r["id"]: r["number"] for r in conn.execute("SELECT id, number FROM projects").fetchall()}
    for position, line in enumerate(lines):
        project_id = line["project_id"] if line["project_id"] in known else None   # a calculation that is gone is let go
        conn.execute(
            "INSERT INTO order_lines (order_id, position, project_id, project_number, description, quantity, unit_price, vat_pct, "
            "cost_price, margin_pct, optional) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (order_id, position, project_id, known.get(project_id) if project_id else line.get("project_number"),
             line["description"], line["quantity"], line["unit_price"], line["vat_pct"], line.get("cost_price"), line.get("margin_pct"),
             line["optional"]))


def _lines_of(conn, order_ids: list) -> dict:
    by_order: dict = {oid: [] for oid in order_ids}
    if order_ids:
        rows = conn.execute("SELECT * FROM order_lines WHERE order_id IN (SELECT value FROM json_each(%s)) ORDER BY order_id, position", (id_list(order_ids),)).fetchall()
        for row in rows:
            by_order[row["order_id"]].append(row)
    return by_order


def _effective_margin(line: dict, rounding: str):
    """The margin a line really makes (rounding can lift it above the one typed), or None for a line with a price of its own."""
    if line["cost_price"] is None:
        return None
    return str(calc.price_from_cost(line["cost_price"], line["margin_pct"], line["vat_pct"], rounding)["margin_pct_effective"])


def _present(order: dict, lines: list) -> dict:
    totals = compute_totals(lines)
    out = _serialise(order)
    out["lines"] = [{**_serialise({k: v for k, v in line.items() if k not in ("order_id",)}), "line_total": totals["line_totals"][i],
                     "margin_pct_effective": _effective_margin(line, order["price_rounding"])}
                    for i, line in enumerate(lines)]
    out["totals"] = totals
    return out


def _with_pdf_flag(conn, order: dict, presented: dict) -> dict:
    presented["has_invoice_pdf"] = conn.execute("SELECT 1 FROM invoice_pdfs WHERE order_id = %s", (order["id"],)).fetchone() is not None
    return presented


def _fetch(conn, order_id):
    order = conn.execute("SELECT * FROM orders WHERE id = %s", (order_id,)).fetchone()
    if order is None:
        raise ApiError(404, "err.order_not_found")
    return order, _lines_of(conn, [order_id])[order_id]


# --- API --------------------------------------------------------------------------------------------------------

@bp.get("")
def list_orders():
    status = request.args.get("status", "")
    query = (request.args.get("q") or "").strip()
    where, params = [], []
    if status:
        if status not in STATUSES:
            raise ApiError(400, "err.order_status")
        where.append("status = %s")
        params.append(status)
    if query:
        like = f"%{query.replace('%', '').replace('_', '')}%"
        where.append("(customer_name ILIKE %s OR customer_number ILIKE %s OR city ILIKE %s OR CAST(number AS TEXT) = %s OR invoice_number ILIKE %s)")
        params += [like, like, like, query.lstrip("#"), like]
    sql = "SELECT * FROM orders" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY order_date DESC, number DESC"
    with pool().connection() as conn:
        orders = conn.execute(sql, params).fetchall()
        lines = _lines_of(conn, [o["id"] for o in orders])
    out = []
    for order in orders:
        totals = compute_totals(lines[order["id"]])
        item = _serialise({k: order[k] for k in ("id", "number", "status", "order_date", "delivery_date", "customer_id", "customer_name", "customer_number", "city",
                                                  "invoice_number", "invoice_date", "updated_at")})
        item.update(line_count=len(lines[order["id"]]), total=totals["total"])
        out.append(item)
    return jsonify(out)


@bp.post("/totals")
def totals():
    """The prices and totals of lines that are being edited, so the screen shows what the server will store."""
    body = json_body()
    raw = body.get("lines", [])
    if not isinstance(raw, list) or len(raw) > MAX_LINES:
        raise ApiError(400, "err.order_lines", max=MAX_LINES)
    rounding = _rounding(body.get("price_rounding"))
    lines = [_line(line, n, rounding) for n, line in enumerate(raw, 1)]
    return jsonify({**compute_totals(lines), "priced_lines": [{"unit_price": str(l["unit_price"]), "margin_pct_effective": l["margin_pct_effective"]} for l in lines]})


def _order_with_customer(conn, body: dict) -> dict:
    """The order in `body`, validated, with the details of the customer it names copied in (an order always has a customer)."""
    try:
        customer_id = uuid.UUID(str(body.get("customer_id")))
    except ValueError:
        raise ApiError(400, "err.order_customer") from None
    customer = conn.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()
    if customer is None:
        raise ApiError(400, "err.order_customer")
    values = validated_order({**body, **customers.snapshot(customer)})
    values["customer_id"] = customer_id
    return values


@bp.post("")
def create_order():
    with pool().connection() as conn:
        values = _order_with_customer(conn, json_body())
        fields = ("number", *ORDER_FIELDS, "customer_id")
        order = conn.execute(f"INSERT INTO orders ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))}) RETURNING *",
                             (next_number(conn, "order"), *(values[f] for f in ORDER_FIELDS), values["customer_id"])).fetchone()     # an invoice date only exists once there is an invoice
        _write_lines(conn, order["id"], values["lines"])
        order, lines = _fetch(conn, order["id"])
    return jsonify(_present(order, lines)), 201


@bp.get("/<uuid:order_id>")
def get_order(order_id):
    with pool().connection() as conn:
        order, lines = _fetch(conn, order_id)
        presented = _with_pdf_flag(conn, order, _present(order, lines))
    return jsonify(presented)


@bp.put("/<uuid:order_id>")
def update_order(order_id):
    body = json_body()
    with pool().connection() as conn:
        current, _ = _fetch(conn, order_id)
        values = _order_with_customer(conn, body)
        fields = (*ORDER_FIELDS, "customer_id")
        sets = ", ".join(f"{f} = %s" for f in fields)
        invoice_date = values["invoice_date"] if current["invoice_number"] else None
        conn.execute(f"UPDATE orders SET {sets}, invoice_date = COALESCE(%s, invoice_date), updated_at = now() WHERE id = %s",
                     (*[values[f] for f in fields], invoice_date, order_id))
        conn.execute("DELETE FROM order_lines WHERE order_id = %s", (order_id,))
        _write_lines(conn, order_id, values["lines"])
        order, lines = _fetch(conn, order_id)
    return jsonify(_present(order, lines))


@bp.patch("/<uuid:order_id>/status")
def set_status(order_id):
    status = json_body().get("status")
    if status not in STATUSES:
        raise ApiError(400, "err.order_status")
    with pool().connection() as conn:
        row = conn.execute("UPDATE orders SET status = %s, updated_at = now() WHERE id = %s RETURNING id", (status, order_id)).fetchone()
    if row is None:
        raise ApiError(404, "err.order_not_found")
    return jsonify({"ok": True, "status": status})


@bp.delete("/<uuid:order_id>")
def delete_order(order_id):
    with pool().connection() as conn:
        row = conn.execute("DELETE FROM orders WHERE id = %s RETURNING id", (order_id,)).fetchone()
    if row is None:
        raise ApiError(404, "err.order_not_found")
    return jsonify({"ok": True})


# --- the invoice ------------------------------------------------------------------------------------------------

def _file_safe(number: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", number)


def _claim_invoice_number(conn, year: int, template: str) -> str:
    """The next number, claimed atomically (two requests never get the same one). It counts per year when the template has
    the year in it, else it keeps counting (under year 0). A number that exists already, because the template was changed
    and changed back, is skipped."""
    scope = year if invoice_numbers.uses_year(template) else 0
    for _ in range(1000):
        last = conn.execute("INSERT INTO invoice_counters (year, last) VALUES (%s, 1) ON CONFLICT (year) DO UPDATE "
                            "SET last = invoice_counters.last + 1 RETURNING last", (scope,)).fetchone()["last"]
        candidate = invoice_numbers.render(template, year, last)
        if not conn.execute("SELECT 1 FROM orders WHERE invoice_number = %s", (candidate,)).fetchone():
            return candidate
    raise ApiError(409, "invoice.number_exhausted")


@bp.post("/<uuid:order_id>/invoice")
def make_invoice(order_id):
    """The invoice of this order as a PDF: the first time it gets its number and date, after that the same ones, with whatever the
    order says now. The PDF is kept (`invoice_pdfs`); a Word template is turned into a PDF first. When that fails nothing is kept,
    not even the number."""
    with pool().connection() as conn:
        order, lines = _fetch(conn, order_id)
        if not lines:
            raise ApiError(409, "invoice.no_lines")
        business = preferences.shared(conn).get("business") or {}
        if not order["invoice_number"]:
            today = date.today()
            invoice_date = order["invoice_date"] or today
            template_text = business.get("invoice_number_format") or invoice_numbers.DEFAULT
            order = conn.execute("UPDATE orders SET invoice_number = %s, invoice_date = %s, updated_at = now() WHERE id = %s RETURNING *",
                                 (_claim_invoice_number(conn, invoice_date.year, template_text), invoice_date, order_id)).fetchone()
        template = invoice_template.load(conn)
        logo = invoice_logo.load(conn)
        try:
            lines = sorted(lines, key=lambda line: line["optional"])      # the optional lines (accessories) come after the others, stable
            content, _mimetype, extension = invoice_docs.render_invoice(order, lines, compute_totals(lines), business, template, logo)
            if extension == "docx":                                  # a Word template gives a Word file; the invoice itself is a PDF
                content = invoice_docs.docx_to_pdf(content)
        except invoice_docs.InvoiceError as exc:
            raise ApiError(422, exc.key, **exc.params) from None
        conn.execute("INSERT INTO invoice_pdfs (order_id, invoice_number, content, size_bytes) VALUES (%s, %s, %s, %s) "
                     "ON CONFLICT (order_id) DO UPDATE SET invoice_number = EXCLUDED.invoice_number, content = EXCLUDED.content, "
                     "size_bytes = EXCLUDED.size_bytes, created_at = now()",
                     (order_id, order["invoice_number"], content, len(content)))
    return _pdf_response(order["invoice_number"], content)


def _pdf_response(number: str, content: bytes) -> Response:
    return Response(content, mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="Factuur-{_file_safe(number)}.pdf"'})


@bp.get("/<uuid:order_id>/invoice")
def get_invoice(order_id):
    """The invoice as it was made (the PDF kept when it was made), without making it again."""
    with pool().connection() as conn:
        row = conn.execute("SELECT invoice_number, content FROM invoice_pdfs WHERE order_id = %s", (order_id,)).fetchone()
    if row is None:
        raise ApiError(404, "invoice.err_no_pdf")
    return _pdf_response(row["invoice_number"], bytes(row["content"]))
