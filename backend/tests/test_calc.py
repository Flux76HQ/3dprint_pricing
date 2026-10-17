import pytest

from app.calc import calculate


def spreadsheet_example():
    """The 'USW-Ultra 10-inch rack-mount' sheet: ABS 70 g, 3 h, printer 3000 h life."""
    return {
        "filament": [{"label": "Bambu ABS Basis Black", "grams": 70, "price_per_kg": "26.99"}],
        "parts": [],
        "print": {
            "depreciation": [{"label": "Afschrijving printer", "hours": 3, "price_per_hour": "0.25"}],
            "energy": [{"label": "USW-Ultra 10-inch rack-mount", "hours": 3, "kw": "0.15",
                        "price_per_kwh": "0.22"}],
        },
    }


def test_matches_the_spreadsheet_line_by_line():
    out = calculate(spreadsheet_example())
    assert out["filament"][0]["cost"] == "1.89"
    assert out["depreciation"][0]["cost"] == "0.75"
    assert out["energy"][0]["cost"] == "0.10"
    assert out["subtotals"]["filament"] == "1.89"
    assert out["subtotals"]["energy_and_depreciation"] == "0.85"
    assert out["cost_price"] == "2.74"


def test_lines_are_rounded_before_summing_so_the_screen_adds_up():
    data = {"filament": [{"grams": 1, "price_per_kg": "5"}] * 3}  # 0.005 each
    out = calculate(data)
    assert [line["cost"] for line in out["filament"]] == ["0.01", "0.01", "0.01"]
    assert out["cost_price"] == "0.03"


def test_parts_and_charger_are_separate_subtotals():
    out = calculate({"parts": [
        {"label": "Magneten", "group": "onderdeel", "quantity": 4, "unit": "stuks", "unit_price": "0.50"},
        {"label": "Kabel", "group": "oplader", "quantity": 1.5, "unit": "m", "unit_price": "2"},
        {"label": "Lijm", "group": "onderdeel", "quantity": 20, "unit": "g", "unit_price": "30"},  # per kg
    ]})
    assert [p["cost"] for p in out["parts"]] == ["2.00", "3.00", "0.60"]
    assert out["subtotals"]["parts"] == "2.60"
    assert out["subtotals"]["charger"] == "3.00"
    assert out["subtotals"]["parts_and_charger"] == "5.60"


def test_margin_gives_a_sell_price():
    out = calculate(spreadsheet_example(), margin_pct=50)
    assert out["margin_amount"] == "1.37"
    assert out["sell_price"] == "4.11"


def test_empty_calculation_is_zero():
    assert calculate({})["cost_price"] == "0"


@pytest.mark.parametrize("data, message", [
    ({"filament": [{"grams": -1, "price_per_kg": 10}]}, "gram"),
    ({"filament": [{"grams": "abc", "price_per_kg": 10}]}, "geen getal"),
    ({"parts": [{"quantity": 1, "unit": "lb", "unit_price": 1}]}, "eenheid"),
    ({"parts": [{"quantity": 1, "group": "x", "unit_price": 1}]}, "groep"),
    ({"filament": "nope"}, "lijst"),
    ({"filament": [{"grams": "NaN", "price_per_kg": 10}]}, "gram"),
])
def test_rejects_bad_input_with_a_readable_message(data, message):
    with pytest.raises(ValueError, match=message):
        calculate(data)


def test_negative_margin_rejected():
    with pytest.raises(ValueError, match="Marge"):
        calculate({}, margin_pct=-5)


def test_packaging_is_its_own_subtotal_and_counts_towards_the_cost_price():
    data = spreadsheet_example()
    data["parts"] = [
        {"label": "Doos", "group": "verpakking", "quantity": 1, "unit": "stuks", "unit_price": "0.85"},
        {"label": "Bubbeltjesplastic", "group": "verpakking", "quantity": 0.5, "unit": "m", "unit_price": "1.20"},
        {"label": "Magneten", "group": "onderdeel", "quantity": 2, "unit": "stuks", "unit_price": "0.40"},
    ]
    out = calculate(data)
    assert out["subtotals"]["packaging"] == "1.45"
    assert out["subtotals"]["parts"] == "0.80"          # packaging is not mixed into parts
    assert out["subtotals"]["parts_and_charger"] == "0.80"
    assert out["cost_price"] == "4.99"                  # 2.74 + 0.80 + 1.45


def test_vat_is_charged_on_the_selling_price_not_the_cost_price():
    out = calculate(spreadsheet_example(), margin_pct=50, vat_pct=21)
    assert out["sell_price"] == "4.11"                 # excl. VAT: 2.74 + 1.37
    assert out["vat_amount"] == "0.86"                 # 4.11 x 21% = 0.8631
    assert out["sell_price_incl_vat"] == "4.97"
    assert out["cost_price"] == "2.74"                 # unaffected


def test_vat_without_margin_applies_to_the_cost_price_as_selling_price():
    out = calculate(spreadsheet_example(), vat_pct=9)
    assert (out["sell_price"], out["vat_amount"], out["sell_price_incl_vat"]) == ("2.74", "0.25", "2.99")


def test_no_vat_by_default_and_zero_is_none():
    for out in (calculate(spreadsheet_example()), calculate(spreadsheet_example(), vat_pct=0)):
        assert out["vat_amount"] == "0.00" and out["sell_price_incl_vat"] == out["sell_price"]


@pytest.mark.parametrize("vat", [-1, 101, "abc", "NaN"])
def test_bad_vat_is_refused(vat):
    with pytest.raises(ValueError, match="BTW"):
        calculate({}, vat_pct=vat)


from decimal import Decimal  # noqa: E402

from app.calc import ROUNDINGS, round_up_price  # noqa: E402


@pytest.mark.parametrize("rule, value, expected", [
    ("0.05", "4.97", "5.00"), ("0.05", "4.95", "4.95"), ("0.10", "4.91", "5.00"), ("0.50", "4.51", "5.00"),
    ("1.00", "4.01", "5.00"), ("5.00", "5.01", "10.00"), ("x.95", "4.97", "5.95"), ("x.95", "4.90", "4.95"),
    ("x.95", "4.95", "4.95"), ("x.99", "5.00", "5.99"), ("x.95", "0.10", "0.95"), ("none", "4.97", "4.97"),
])
def test_round_up_price(rule, value, expected):
    assert round_up_price(Decimal(value), rule) == Decimal(expected)


def test_rounding_lifts_the_margin_so_the_price_incl_vat_is_round():
    out = calculate(spreadsheet_example(), margin_pct=50, vat_pct=21, rounding="0.50")
    assert out["sell_price_incl_vat"] == "5.00"          # was 4.97
    assert out["vat_amount"] == "0.87" and out["sell_price"] == "4.13"
    assert out["margin_amount"] == "1.39" and out["margin_pct_effective"] == "50.73"
    assert out["margin_pct"] == "50"                      # what was typed is kept, as the minimum
    charm = calculate(spreadsheet_example(), margin_pct=50, vat_pct=21, rounding="x.95")
    assert charm["sell_price_incl_vat"] == "5.95" and charm["sell_price"] == "4.92"


def test_rounding_without_vat_rounds_the_selling_price():
    out = calculate(spreadsheet_example(), margin_pct=50, rounding="0.50")
    assert out["sell_price"] == "4.50" and out["vat_amount"] == "0.00" and out["sell_price_incl_vat"] == "4.50"


def test_rounding_never_lowers_the_price_and_always_lands_on_the_rule():
    for cost in ("0.37", "2.74", "13.99", "120.01"):
        for margin in (0, 10, 33, 50, 100):
            for vat in (0, 9, 21):
                for rule in ROUNDINGS[1:]:
                    data = {"filament": [{"grams": 1000, "price_per_kg": cost}]}
                    base = calculate(data, margin, vat)
                    out = calculate(data, margin, vat, rule)
                    incl, floor_ = Decimal(out["sell_price_incl_vat"]), Decimal(base["sell_price_incl_vat"])
                    assert incl >= floor_, (cost, margin, vat, rule)
                    assert Decimal(out["sell_price"]) + Decimal(out["vat_amount"]) == incl
                    assert Decimal(out["margin_amount"]) >= Decimal(base["margin_amount"]), (cost, margin, vat, rule)
                    assert round_up_price(incl, rule) == incl, (cost, margin, vat, rule)   # already on the rule


def test_rounding_an_empty_calculation_stays_zero_and_bad_rules_are_refused():
    assert calculate({}, 50, 21, "x.95")["sell_price_incl_vat"] == "0.00"
    with pytest.raises(ValueError, match="Afronding"):
        calculate({}, rounding="0.07")


@pytest.mark.parametrize("hours, billed", [("3", "3"), ("3.06", "4"), ("0.2", "1"), ("0", "0"), ("12.999", "13")])
def test_machine_time_is_always_charged_in_whole_hours_rounded_up(hours, billed):
    data = spreadsheet_example()
    data["print"]["depreciation"][0]["hours"] = hours
    data["print"]["energy"][0]["hours"] = hours
    out = calculate(data)
    assert out["depreciation"][0]["hours_billed"] == billed and out["energy"][0]["hours_billed"] == billed
    assert out["depreciation"][0]["cost"] == str((Decimal(billed) * Decimal("0.25")).quantize(Decimal("0.01")))


def test_the_slicers_3_06_hours_cost_four_hours_of_depreciation_and_energy():
    data = spreadsheet_example()
    data["print"]["depreciation"][0]["hours"] = 3.06
    data["print"]["energy"][0]["hours"] = 3.06
    out = calculate(data)
    assert out["subtotals"]["depreciation"] == "1.00" and out["subtotals"]["energy"] == "0.13"   # 4 x 0.25; 4 x 0.15 x 0.22
