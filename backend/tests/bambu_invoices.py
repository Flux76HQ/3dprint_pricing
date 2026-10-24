"""A synthetic Bambu Lab invoice (PDF), laid out like the shop's: one text line per row, in the order pypdf reads the real one
(the item rows of a page first, then the address block). No real name, address or order is in here; a real invoice is the final check."""
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HEADER = "Items Qty Price Product discount Tax Tax amount Items SubTotal"
ADDRESS = ["INVOICE", "INVOICE TO", "Test Klant", "Teststraat 1,Teststad,1234 AB,Netherlands", "Bambu Lab EU", "Bambulab GmbH",
           "Invoice Number: BBLEU25000000AAAA1", "Order Number: EN000000000000000001", "Invoice Date: 2025-12-07"]

# (name, sku lines, variant lines, qty, price, discount, vat, tax amount, subtotal)
FILAMENT = [
    ("PLA Basic", ["A00-D0-1.75-1000-", "SPLFREE"], ["Grijs (10103) / Bijvullen", "/ 1kg"], 1, "23.38", "12.39", "21", "1.91", "10.99"),
    ("PLA Basic", ["A00-R0-1.75-1000-SPL"], ["Rood (10200) / Filament ", "met spoel / 1kg"], 2, "26.43", "28.02", "21", "4.31", "24.84"),
    ("PLA Matte", ["A01-R3-1.75-1000-", "SPLFREE"], ["Pruim (11204) / Bijvullen", "/ 1kg"], 1, "23.38", "12.39", "21", "1.91", "10.99"),
]
HOTEND = ("Hotend", ["HT-A1-04"], ["0.4 mm"], 1, "19.00", "0.00", "21", "3.30", "19.00")


def lines_of(items, total="46.82", *, bambu=True):
    rows = [HEADER]
    for name, sku, variant, qty, price, discount, vat, tax, subtotal in items:
        rows += [name, "SKU: " + sku[0], *sku[1:], "Variant: " + variant[0], *variant[1:],
                 f"{qty} €{price} €{discount} NL btw({vat}%) €{tax} €{subtotal}"]
    rows += ADDRESS if bambu else ["INVOICE", "Some Other Shop", "Order Number: 1"]
    rows += [f"Items Subtotal €{total}", "Shipping €0.00", f"Grand total €{total}"]
    return rows


def pdf_of(rows, *, encrypt=None) -> bytes:
    out = BytesIO()
    page = canvas.Canvas(out, pagesize=A4, **({"encrypt": encrypt} if encrypt else {}))
    y = 800
    for row in rows:
        page.drawString(40, y, row)
        y -= 14
    page.save()
    return out.getvalue()


def invoice_pdf(items=None, *, total=None, bambu=True, encrypt=None) -> bytes:
    items = FILAMENT if items is None else items
    total = total or f"{sum(float(i[8]) for i in items):.2f}"
    return pdf_of(lines_of(items, total, bambu=bambu), encrypt=encrypt)
