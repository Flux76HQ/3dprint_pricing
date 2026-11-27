"""Reading a Bambu Lab invoice: the filament lines, the money, and everything that is not one."""
from decimal import Decimal

import pytest

from app import bambu_invoice
from app.i18n import Localized
from tests.bambu_invoices import FILAMENT, HOTEND, invoice_pdf, item_rows, lines_of, pdf_of


def read(items=None, **kwargs):
    return bambu_invoice.read(invoice_pdf(items, **kwargs))


def test_the_filament_lines_come_out_with_their_specs():
    invoice = read()
    assert (invoice["order_number"], invoice["invoice_number"], invoice["invoice_date"]) == ("EN000000000000000001", "BBLEU25000000AAAA1", "2025-12-07")
    grey, red, plum = invoice["lines"]
    assert (grey["brand"], grey["material"], grey["product_type"], grey["colour"], grey["filament_id"]) == ("Bambu Lab", "PLA", "Basic", "Grijs", "10103")
    assert (grey["sku"], grey["refill"], grey["roll_weight_g"], grey["diameter_mm"], grey["quantity"]) == ("A00-D0-1.75-1000-SPLFREE", True, "1000", "1.75", 1)
    assert (red["sku"], red["refill"], red["colour"], red["quantity"]) == ("A00-R0-1.75-1000-SPL", False, "Rood", 2)    # a SKU cut at a hyphen is joined again
    assert (plum["product_type"], plum["filament_id"]) == ("Matte", "11204")


def test_the_price_is_the_list_price_excl_vat_not_what_a_promotion_made_of_it():
    grey, red, _ = read()["lines"]
    assert grey["price"] == "19.32" and "paid_price" not in grey             # 23.38 incl. VAT is 19.32 excl.; the 12.39 discount is a promotion
    assert red["price"] == "21.84" and red["vat_pct"] == "21" and red["subtotal"] == "24.84"


def test_the_lines_add_up_to_the_invoice_total():
    invoice = read()
    assert invoice["total"] == invoice["lines_total"] == "46.82"
    assert read(total="50.00")["total"] != read(total="50.00")["lines_total"]


def test_a_line_that_is_not_filament_is_skipped_and_named():
    invoice = read([*FILAMENT, HOTEND])
    assert len(invoice["lines"]) == 3 and invoice["skipped"] == ["Hotend"]
    assert invoice["total"] == invoice["lines_total"]                       # the skipped line is still part of the total


def test_the_material_is_split_from_the_name():
    assert bambu_invoice.split_name("PLA Basic") == ("PLA", "Basic")
    assert bambu_invoice.split_name("PETG HF") == ("PETG", "HF")
    assert bambu_invoice.split_name("PLA-CF") == ("PLA-CF", "")
    assert bambu_invoice.split_name("Support for PLA") == ("", "Support for PLA")


@pytest.mark.parametrize("text, expected", [("23.38", "23.38"), ("23,38", "23.38"), ("1.234,56", "1234.56"), ("1,234.56", "1234.56")])
def test_amounts_are_read_with_a_point_or_a_comma(text, expected):
    assert bambu_invoice.money(text) == Decimal(expected)


def test_weight_and_refill_come_from_the_variant_when_the_sku_does_not_say():
    row = ("PETG HF", ["X-ODD"], ["Zwart (31100) / Bijvullen / 2kg"], 1, "30.00", "0.00", "21", "5.21", "30.00")
    line = read([row])["lines"][0]
    assert (line["roll_weight_g"], line["refill"], line["diameter_mm"], line["material"]) == ("2000", True, "1.75", "PETG")


@pytest.mark.parametrize("content, key", [
    (b"not a pdf", "bambu.err_not_pdf"),
    (b"%PDF-1.4 but broken", "bambu.err_unreadable"),
    (b"%PDF" + b"0" * (bambu_invoice.MAX_BYTES + 1), "bambu.err_too_big"),
    (pdf_of(lines_of(FILAMENT, "1", bambu=False)), "bambu.err_not_bambu"),
    (pdf_of(["Bambu Lab", "nothing to buy here"]), "bambu.err_no_items"),
    (invoice_pdf(encrypt="secret"), "bambu.err_encrypted"),
])
def test_what_is_not_a_readable_bambu_invoice_is_refused_with_a_reason(content, key):
    with pytest.raises(Localized) as refused:
        bambu_invoice.read(content)
    assert refused.value.msg.key == key


# --- an item that falls on a page break ------------------------------------------------------------------------------

PLAIN = None


def read_plain():
    global PLAIN
    PLAIN = PLAIN or read(FILAMENT)
    return PLAIN


@pytest.mark.parametrize("order", ["normal", "numbers-early"])
@pytest.mark.parametrize("item", [0, 1, 2])
def test_an_item_that_a_page_break_cuts_is_read_the_same_wherever_it_is_cut(item, order):
    """The same invoice, with the page ending after each row of one item in turn (and before it, and after it): the lines are those of the invoice without a break,
    also the item after the break. `numbers-early` is how the real one fell: name, SKU and numbers on one page, the variant under the repeated header of the next."""
    plain = read_plain()
    for after in range(len(item_rows(FILAMENT[item])) + 1):
        cut = read(FILAMENT, split={"item": item, "after": after, "order": order})
        assert (cut["lines"], cut["skipped"], cut["lines_total"]) == (plain["lines"], plain["skipped"], plain["lines_total"]), (item, order, after)


def test_the_colour_of_an_item_whose_variant_is_on_the_next_page_is_read():
    cut = read(FILAMENT, split={"item": 0, "after": 4, "order": "numbers-early"})              # name, SKU, SKU, numbers | header | variant, variant
    assert [(l["colour"], l["filament_id"], l["refill"], l["material"], l["product_type"]) for l in cut["lines"]] == [
        ("Grijs", "10103", True, "PLA", "Basic"), ("Rood", "10200", False, "PLA", "Basic"), ("Pruim", "11204", True, "PLA", "Matte")]


@pytest.mark.parametrize("item", [0, 1, 2])
@pytest.mark.parametrize("footer", [["Pagina 1 van 2"], ["Pagina 1 van 2", "Bambu Lab"]])
def test_a_page_footer_before_the_repeated_header_does_not_end_up_in_the_next_name(item, footer):
    """Between two items (after the last row of one, which is before the first of the next) a page ends with a footer: what the next item is called is not touched."""
    plain = read_plain()
    for after in (0, len(item_rows(FILAMENT[item]))):
        if (item, after) in ((0, 0),):                                                          # before the first item there is nothing to cut off
            continue
        cut = read(FILAMENT, split={"item": item, "after": after, "footer": footer})
        assert cut["lines"] == plain["lines"], (item, after, footer)


ACCESSORY = ("Reinigingsset", ["ACC-1"], [], 1, "5.00", "0.00", "21", "0.87", "5.00")                  # an item with no variant at all


@pytest.mark.parametrize("split", [None, {"item": 1, "after": 3}, {"item": 2, "after": 0}, {"item": 1, "after": 2, "order": "numbers-early"}])
def test_an_item_without_a_variant_stays_without_one_and_takes_nothing_of_the_next(split):
    cut = read([FILAMENT[0], ACCESSORY, FILAMENT[1]], split=split)
    assert [l["colour"] for l in cut["lines"]] == ["Grijs", "Rood"] and cut["skipped"] == ["Reinigingsset"]
    assert (cut["lines"][1]["name"], cut["lines"][1]["material"], cut["lines"][1]["product_type"]) == ("PLA Basic", "PLA", "Basic")


@pytest.mark.parametrize("split", [None, {"item": 1, "after": 2, "order": "numbers-early"}, {"item": 1, "after": 5, "order": "numbers-early"}])
def test_a_variant_without_a_weight_that_follows_the_numbers_does_not_take_the_next_name(split):
    hotend = ("Hotend", ["HT-A1-04"], ["0.4 mm"], 1, "19.00", "0.00", "21", "3.30", "19.00")
    cut = read([FILAMENT[0], hotend, FILAMENT[1]], split={**split, "order": "numbers-early"} if split else {"item": 1, "after": 0, "order": "numbers-early"})
    assert [l["colour"] for l in cut["lines"]] == ["Grijs", "Rood"] and cut["skipped"] == ["Hotend"]
    assert cut["lines"][1]["name"] == "PLA Basic" and cut["lines"][1]["material"] == "PLA"


def test_a_one_row_variant_that_follows_the_numbers_ends_at_its_weight_before_a_name_that_also_ends_in_one():
    one_row = ("PLA Basic", ["A00-D0-1.75-1000-SPLFREE"], ["Grijs (10103) / Bijvullen / 1kg"], 1, "23.38", "12.39", "21", "1.91", "10.99")
    named_in_kg = ("PETG HF 1kg", ["G02-K0-1.75-1000-SPL"], ["Zwart (33102) / Filament met spoel / 1kg"], 1, "26.43", "0.00", "21", "4.59", "26.43")
    cut = read([one_row, named_in_kg], split={"item": 0, "after": 4, "order": "numbers-early"})       # name, SKU, numbers, variant | header | next item
    assert [(l["name"], l["colour"], l["filament_id"]) for l in cut["lines"]] == [("PLA Basic", "Grijs", "10103"), ("PETG HF 1kg", "Zwart", "33102")]


def test_an_item_whose_numbers_are_the_last_thing_in_the_text_is_still_made():
    rows = ["Bambu Lab", "Items Qty Price Product discount Tax Tax amount Items SubTotal", "PLA Basic", "SKU: A00-D0-1.75-1000-SPLFREE",
            "1 €23.38 €12.39 NL btw(21%) €1.91 €10.99"]
    [line] = bambu_invoice.parse("\n".join(rows))["lines"]
    assert (line["name"], line["sku"], line["colour"]) == ("PLA Basic", "A00-D0-1.75-1000-SPLFREE", "")
