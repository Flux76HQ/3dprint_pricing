"""Read a Bambu Lab webshop invoice (PDF) and turn its filament lines into library entries.

An invoice is an untrusted upload: it is opened only by pypdf, capped in size and pages, and every failure becomes a `Localized`
error the user can act on. Nothing here touches the database; `filament_library` decides what to do with the result.

What the invoice says (and how it is read):

* *Price* is the shop's list price **including** VAT, *Product discount* is the discount on the whole line and *Items SubTotal* is
  Price x Qty - discount, still including VAT. The roll price the owner works with is excl. VAT, so both the list price and the
  price actually paid per roll (after discount) are given, each excl. VAT.
* The SKU (`A00-D0-1.75-1000-SPLFREE`) carries the diameter and the weight in grams; a SKU ending in `FREE` is a refill (no spool).
  The variant (`Grijs (10103) / Bijvullen / 1kg`) carries the colour, the shop's colour code and, as a fallback, the weight.
* Lines that are not filament (a printer, a hotend...) are skipped and reported.

The layout is the shop's, not ours: `tests/test_bambu_invoice.py` pins it with a synthetic invoice, and a real one is the final check.
"""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO

from pypdf import PdfReader

from .i18n import Localized

BRAND = "Bambu Lab"
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_LINES = 200

MATERIAL = re.compile(r"^(PLA|PETG|PET|ABS|ASA|TPU|PAHT|PPA|PPS|PVA|HIPS|PA\d*|PC)(?:[-+][A-Za-z0-9]+)?(?=\s|$)", re.I)
SKU = re.compile(r"^[A-Z]\d{2}-[A-Z0-9]{1,6}-(\d\.\d{2})-(\d{3,5})-SPL(FREE)?$", re.I)
ITEM = re.compile(r"^(\d{1,4})\s+€\s*([\d.,]+)\s+€\s*([\d.,]+)\s+(.*?)\(\s*(\d+(?:[.,]\d+)?)\s*%\s*\)\s+€\s*([\d.,]+)\s+€\s*([\d.,]+)$")
REFILL = re.compile(r"bijvul|refill|nachf|recharge|recambio|ricarica", re.I)
VARIANT = re.compile(r"^(.*?)\s*\(\s*([A-Za-z0-9-]{3,10})\s*\)$")
WEIGHT = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.I)
CENT = Decimal("0.01")


def money(value: str) -> Decimal:
    """'23.38', '23,38' and '1.234,56' are all amounts; anything else is not one."""
    value = value.strip()
    if "," in value and "." in value:
        decimal = "," if value.rfind(",") > value.rfind(".") else "."
        value = value.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise Localized("bambu.err_unreadable") from None


def text_of(content: bytes) -> str:
    """All the text of the PDF; raises Localized when it is not a PDF we can read."""
    if len(content) > MAX_BYTES:
        raise Localized("bambu.err_too_big", mb=MAX_BYTES // (1024 * 1024))
    if not content.startswith(b"%PDF"):
        raise Localized("bambu.err_not_pdf")
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise Localized("bambu.err_encrypted")
        if len(reader.pages) > MAX_PAGES:
            raise Localized("bambu.err_pages", n=MAX_PAGES)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Localized:
        raise
    except Exception:
        raise Localized("bambu.err_unreadable") from None


def split_name(name: str) -> tuple[str, str]:
    """'PLA Basic' -> ('PLA', 'Basic'); a name that does not start with a material is all type."""
    found = MATERIAL.match(name.strip())
    if not found:
        return "", name.strip()
    material = found.group(0)
    return material, name.strip()[len(material):].strip()


def _excl(amount_incl: Decimal, vat_pct: Decimal) -> Decimal:
    return (amount_incl / (1 + vat_pct / 100)).quantize(CENT, ROUND_HALF_UP)


def _parts(buf: list[str]) -> tuple[str, str, str]:
    """(name, SKU, variant) from the rows above an item's numbers; a SKU is cut at a hyphen, a variant at a space."""
    name, sku, variant, target = [], [], [], None
    for text in buf:
        if text.upper().startswith("SKU:"):
            target = sku
            text = text[4:]
        elif text.lower().startswith("variant:"):
            target = variant
            text = text[8:]
        (name if target is None else target).append(text.strip())
    return " ".join(name).strip(), "".join("".join(sku).split()), " ".join(" ".join(variant).split())


def _line(buf: list[str], numbers: tuple) -> "dict | None":
    """One invoice line from the text above its numbers; None when it is not filament."""
    qty, price, discount, _tax_name, vat, _tax, subtotal = numbers
    name, sku, variant = _parts(buf)
    material, product_type = split_name(name)
    sku_found = SKU.match(sku)
    if not sku_found and not material:
        return None

    parts = [p.strip() for p in variant.split(" / ")]
    named = VARIANT.match(parts[0]) if parts and parts[0] else None
    colour, code = (named.group(1), named.group(2)) if named else (parts[0] if parts else "", "")
    refill = bool(sku_found and sku_found.group(3)) or bool(REFILL.search(variant))
    if sku_found:
        diameter, weight = Decimal(sku_found.group(1)), Decimal(sku_found.group(2))
    else:
        kg = WEIGHT.search(variant)
        diameter, weight = Decimal("1.75"), (money(kg.group(1)) * 1000 if kg else Decimal(1000))

    vat_pct = money(vat)
    quantity = int(qty)
    paid = money(subtotal) / quantity
    return {"brand": BRAND, "material": material, "product_type": product_type, "colour": colour, "filament_id": code, "sku": sku,
            "refill": refill, "roll_weight_g": str(weight), "diameter_mm": str(diameter), "quantity": quantity, "vat_pct": str(vat_pct),
            "price": str(_excl(money(price), vat_pct)),                    # the list price per roll, excl. VAT: the library's reference
            "paid_price": str(_excl(paid, vat_pct)),                       # what a roll really cost after the discount, excl. VAT
            "discount": str(money(discount)), "subtotal": str(money(subtotal)), "name": name}


def parse(text: str) -> dict:
    """The invoice's details and its filament lines. Raises Localized when this is not a Bambu Lab invoice with items."""
    if not re.search(r"bambu\s?lab", text, re.I):
        raise Localized("bambu.err_not_bambu")
    lines, skipped, buf, summed = [], [], [], Decimal(0)
    for raw in text.splitlines():
        row = " ".join(raw.split())
        if not row:
            continue
        if row.startswith("Items Qty"):                        # the header of the table: what came before it is not an item
            buf = []
            continue
        found = ITEM.match(row)
        if not found:
            buf.append(row)
            continue
        numbers = found.groups()
        summed += money(numbers[-1])
        line = _line(buf, numbers)
        if line:
            lines.append(line)
        else:
            skipped.append(_parts(buf)[0][:120])
        buf = []
        if len(lines) + len(skipped) > MAX_LINES:
            raise Localized("bambu.err_unreadable")
    if not lines and not skipped:
        raise Localized("bambu.err_no_items")

    def find(pattern: str) -> "str | None":
        found = re.search(pattern, text)
        return found.group(1) if found else None

    total = find(r"Items Subtotal\s*€\s*([\d.,]+)")
    return {"brand": BRAND, "order_number": find(r"Order Number:\s*(\S+)"), "invoice_number": find(r"Invoice Number:\s*(\S+)"),
            "invoice_date": find(r"Invoice Date:\s*(\d{4}-\d{2}-\d{2})"), "lines": lines, "skipped": skipped,
            "total": str(money(total)) if total else None,
            "lines_total": str(summed)}


def read(content: bytes) -> dict:
    return parse(text_of(content))
