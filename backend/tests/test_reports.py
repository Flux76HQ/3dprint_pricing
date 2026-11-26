"""The sales overview: revenue (excl. VAT), cost and margin per week, month and year, worked out on the server."""
from datetime import date, timedelta
from decimal import Decimal

from app import reports
from tests.test_auth_api import H
from tests.test_domain_api import owner  # noqa: F401  (fixture)
from tests.test_orders import line, new_order


def sale(owner, quantity=2, cost="5.00", margin="100", vat="21", status="verstuurd", day=None, **extra):
    """An order of one calculated line: `cost` each, with `margin` percent on top, so it is easy to say what it earned."""
    return new_order(owner, [line("Vaas", quantity, "0", vat, cost_price=cost, margin_pct=margin)], status=status,
                     order_date=(day or date.today()).isoformat(), **extra)


def report(owner, **params):
    res = owner.get("/api/reports/sales", query_string=params)
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_margin_is_revenue_excl_vat_minus_cost(owner):
    order = sale(owner, quantity=2, cost="5.00", margin="100", vat="21")           # 2 x (5 + 100%) incl. VAT = 2 x 12.10 = 24.20; net 20.00
    assert order["totals"]["total"] == "24.20"
    totals = report(owner)["totals"]
    assert (totals["orders"], totals["revenue"], totals["cost"], totals["margin"], totals["margin_pct"]) == (1, "20.00", "10.00", "10.00", "50.0")


def test_only_sent_or_done_orders_count_unless_asked(owner):
    sale(owner, status="verstuurd")
    sale(owner, status="afgehandeld")
    sale(owner, status="nieuw")
    sale(owner, status="in_behandeling")
    sale(owner, status="verwerkt")
    assert report(owner)["totals"]["orders"] == 2
    assert report(owner, include_open="true")["totals"]["orders"] == 5


def test_a_line_without_a_cost_price_is_counted_not_guessed(owner):
    new_order(owner, [line("Verzending", 1, "6.05", "21")], status="verstuurd", order_date=date.today().isoformat())
    totals = report(owner)["totals"]
    assert totals["revenue"] == "5.00" and totals["cost"] == "0.00" and totals["unknown_cost_lines"] == 1


def test_week_month_and_year_each_see_their_own_orders(owner):
    today = date.today()
    sale(owner, day=today)
    sale(owner, day=today - timedelta(days=400))                                   # last year only
    first_of_month = today.replace(day=1)
    sale(owner, day=first_of_month)
    now = report(owner)["now"]
    assert now["year"]["orders"] >= 1 and now["month"]["orders"] >= 1
    assert report(owner, period="year", offset=-1)["totals"]["orders"] >= 1
    assert report(owner, period="year")["totals"]["orders"] == now["year"]["orders"]
    assert now["week"]["orders"] <= now["month"]["orders"] or today.day < 7        # a week can reach into last month


def test_windows():
    thursday = date(2026, 11, 26)
    assert reports.window("week", 0, thursday) == (date(2026, 11, 23), date(2026, 11, 29))
    assert reports.window("week", -1, thursday) == (date(2026, 11, 16), date(2026, 11, 22))
    assert reports.window("month", 0, thursday) == (date(2026, 11, 1), date(2026, 11, 30))
    assert reports.window("month", 2, thursday) == (date(2027, 1, 1), date(2027, 1, 31))
    assert reports.window("month", -11, thursday) == (date(2025, 12, 1), date(2025, 12, 31))
    assert reports.window("year", -1, thursday) == (date(2025, 1, 1), date(2025, 12, 31))


def test_buckets_add_up_to_the_totals(owner):
    today = date.today()
    sale(owner, day=today, quantity=1)
    sale(owner, day=today.replace(month=1, day=2), quantity=3)
    for period in ("week", "month", "year"):
        found = report(owner, period=period)
        assert len(found["buckets"]) == {"week": 7, "month": (date.fromisoformat(found["end"]) - date.fromisoformat(found["start"])).days + 1, "year": 12}[period]
        assert sum(Decimal(b["revenue"]) for b in found["buckets"]) == Decimal(found["totals"]["revenue"])
        assert sum(Decimal(b["margin"]) for b in found["buckets"]) == Decimal(found["totals"]["margin"])
        assert sum(b["orders"] for b in found["buckets"]) == found["totals"]["orders"] == len(found["orders"])


def test_the_orders_are_listed_with_their_own_margin(owner):
    sale(owner, quantity=1, cost="10.00", margin="50", vat="0", subject="Pot")
    row = report(owner)["orders"][0]
    assert row["subject"] == "Pot" and row["revenue"] == "15.00" and row["cost"] == "10.00" and row["margin"] == "5.00"


def test_bad_period_and_a_session_are_required(owner, app):
    assert owner.get("/api/reports/sales?period=decade").status_code == 400
    assert owner.get("/api/reports/sales?offset=x").status_code == 400
    assert owner.get("/api/reports/sales?offset=99999").status_code == 400
    assert app.test_client().get("/api/reports/sales").status_code == 401
