"""What the orders earned: the revenue, the cost and the margin that is left, over a week, a month or a year.

Worked out on the server from the stored orders, never in the browser (as the totals of an order are). Money is `Decimal`, each order is
rounded to cents before orders are added, so the rows on the screen add up to the totals above them.

* **Revenue** is what the customer pays *excluding VAT* (the net part of every line, `orders.compute_totals`): VAT is the state's.
* **Cost** is what the lines cost to make: the line's cost price (excl. VAT, copied from its calculation: filament, parts, packaging,
  machine time and energy) times the quantity. A line without a cost price (a free line such as a delivery fee) costs nothing here and
  is counted in `unknown_cost_lines`, so the screen can say that the margin is a little too good where such a line sits.
* **Margin** is revenue minus cost, and `margin_pct` is that margin as a share of the revenue.
* An order counts on its **order date**, and only once it is sent or done (`COUNTED`); `include_open` adds the orders that are not.
"""
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, jsonify, request

from .db import id_list
from .http import ApiError, login_required, pool
from .orders import compute_totals

bp = Blueprint("reports", __name__, url_prefix="/api/reports")

PERIODS = ("week", "month", "year")
COUNTED = ("verstuurd", "afgehandeld")                # an order that is sent or done has earned its money
NOT_YET = ("nieuw", "verwerkt")                        # counted only when asked for
CENT = Decimal("0.01")
MAX_OFFSET = 600                                       # how far back (or on) the period may be moved


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def window(period: str, offset: int, today: date) -> tuple:
    """The first and the last day of the week (Monday to Sunday), month or year that is `offset` periods from the one `today` is in."""
    if period == "week":
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        return start, start + timedelta(days=6)
    if period == "month":
        index = today.year * 12 + today.month - 1 + offset
        year, month = divmod(index, 12)
        return date(year, month + 1, 1), date(year, month + 1, calendar.monthrange(year, month + 1)[1])
    year = today.year + offset
    return date(year, 1, 1), date(year, 12, 31)


def _order_figures(conn, start: date, end: date, statuses: tuple) -> list:
    """Per order that lies in the window: what it brought in, what it cost and what is left."""
    orders = conn.execute(
        "SELECT id, number, status, order_date, customer_name, subject FROM orders "
        "WHERE order_date >= %s AND order_date <= %s AND status IN (SELECT value FROM json_each(%s)) ORDER BY order_date, number",
        (start, end, id_list(statuses))).fetchall()
    lines: dict = {o["id"]: [] for o in orders}
    if orders:
        for row in conn.execute("SELECT order_id, quantity, unit_price, vat_pct, cost_price FROM order_lines "
                                "WHERE order_id IN (SELECT value FROM json_each(%s)) ORDER BY order_id, position",
                                (id_list([o["id"] for o in orders]),)).fetchall():
            lines[row["order_id"]].append(row)
    out = []
    for order in orders:
        mine = lines[order["id"]]
        revenue = Decimal(compute_totals(mine)["total_excl"])
        cost = _money(sum((Decimal(l["cost_price"]) * l["quantity"] for l in mine if l["cost_price"] is not None), Decimal(0)))
        out.append({"id": str(order["id"]), "number": order["number"], "status": order["status"], "order_date": order["order_date"],
                    "customer_name": order["customer_name"], "subject": order["subject"], "revenue": revenue, "cost": cost,
                    "margin": revenue - cost, "unknown_cost_lines": sum(1 for l in mine if l["cost_price"] is None)})
    return out


def _sum(figures: list) -> dict:
    revenue = sum((f["revenue"] for f in figures), Decimal(0))
    cost = sum((f["cost"] for f in figures), Decimal(0))
    margin = revenue - cost
    return {"orders": len(figures), "revenue": str(revenue), "cost": str(cost), "margin": str(margin),
            "margin_pct": str((margin / revenue * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if revenue > 0 else None,
            "unknown_cost_lines": sum(f["unknown_cost_lines"] for f in figures)}


def _buckets(period: str, start: date, end: date, figures: list) -> list:
    """The window cut up for the chart: a bar per day in a week or a month, per month in a year."""
    if period == "year":
        keys = [date(start.year, m, 1) for m in range(1, 13)]
        of = lambda d: date(d.year, d.month, 1)                              # noqa: E731
    else:
        keys = [start + timedelta(days=n) for n in range((end - start).days + 1)]
        of = lambda d: d                                                     # noqa: E731
    found = {k: [] for k in keys}
    for f in figures:
        found[of(f["order_date"])].append(f)
    return [{"date": k.isoformat(), **{x: y for x, y in _sum(found[k]).items() if x in ("orders", "revenue", "cost", "margin")}} for k in keys]


@bp.get("/sales")
def sales():
    """The window the person looks at (`period` and `offset`, 0 = this one, -1 = the one before), cut up for the chart, with its orders,
    and always the totals of this week, this month and this year next to it. `include_open=true` also counts orders that are not sent yet."""
    period = request.args.get("period", "month")
    if period not in PERIODS:
        raise ApiError(400, "err.report_period")
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(400, "err.report_period") from None
    if abs(offset) > MAX_OFFSET:
        raise ApiError(400, "err.report_period")
    statuses = COUNTED + NOT_YET if request.args.get("include_open") in ("1", "true") else COUNTED
    today = date.today()
    start, end = window(period, offset, today)
    with pool().read() as conn:
        figures = _order_figures(conn, start, end, statuses)
        now = {p: _sum(_order_figures(conn, *window(p, 0, today), statuses)) for p in PERIODS}
    return jsonify({"period": period, "offset": offset, "start": start.isoformat(), "end": end.isoformat(), "include_open": len(statuses) > len(COUNTED),
                    "totals": _sum(figures), "buckets": _buckets(period, start, end, figures), "now": now,
                    "orders": [{**f, "order_date": f["order_date"].isoformat(), "revenue": str(f["revenue"]), "cost": str(f["cost"]),
                                "margin": str(f["margin"])} for f in figures]})
