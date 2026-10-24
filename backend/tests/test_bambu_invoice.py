"""Reading a Bambu Lab invoice: the filament lines, the money, and everything that is not one."""
from decimal import Decimal

import pytest

from app import bambu_invoice
from app.i18n import Localized
from tests.bambu_invoices import FILAMENT, HOTEND, invoice_pdf, lines_of, pdf_of


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


def test_prices_are_excl_vat_both_the_list_price_and_what_was_paid():
    grey, red, _ = read()["lines"]
    assert (grey["price"], grey["paid_price"]) == ("19.32", "9.08")          # 23.38 incl. VAT is 19.32; 10.99 paid for one roll incl. VAT is 9.08
    assert (red["price"], red["paid_price"]) == ("21.84", "10.26")           # 24.84 for two rolls: 12.42 each incl. VAT
    assert red["vat_pct"] == "21" and red["subtotal"] == "24.84"


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
