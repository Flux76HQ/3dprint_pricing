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
