"""Making the invoice file: from a Word template, from a PDF used as letter paper, or from the built-in layout.

The built-in layout follows the owner's example invoice: the logo at the top left, the company details right aligned at the top right,
the customer's address on the left, the dates and the customer number on the right, "Factuur: nr" and "Betreft:", a table with the
amount excl. and incl. VAT per line, the totals per VAT rate, the payment sentence and a payment QR code (a SEPA/EPC code that banking
apps read). It is set in Open Sans (`app/fonts`, SIL Open Font License).

A Word template holds `{{placeholders}}` (see PLACEHOLDERS); one table row that contains `{{regel.*}}` placeholders is the row that is
repeated for every order line, and `{{logo}}` / `{{betaal_qr}}` become pictures. A PDF template is only the paper: the invoice is drawn on
its first page (between the top and bottom margins that were set with it), so a letterhead with logo and company details stays as it is.

Everything uploaded is untrusted: size and unpacked size are capped, Word files go through python-docx (which does not resolve XML
entities) and PDFs are only read by pypdf, never executed.
"""
import copy
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import segno
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.text.paragraph import Paragraph
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, Image, NextPageTemplate, PageTemplate, Spacer, Table, TableStyle
from reportlab.platypus import Paragraph as PdfParagraph

from .i18n import DEFAULT_LANGUAGE, LANGUAGES, translate

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024          # a Word file is a zip: what it unpacks to is capped as well
MAX_ZIP_ENTRIES = 2_000
CENT = Decimal("0.01")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)?)\s*\}\}")
FONT_DIR = Path(__file__).parent / "fonts"
IMAGE_TOKENS = ("logo", "betaal_qr")             # filled with a picture, not with text

# What can be put in a Word template. Shown in Settings and in the README; the sample template uses nearly all of them.
PLACEHOLDERS = (
    "logo", "betaal_qr",
    "factuurnummer", "factuurdatum", "vervaldatum", "betreft", "bestelnummer", "besteldatum", "leverdatum", "opmerking",
    "klant.naam", "klant.nummer", "klant.adres", "klant.postcode", "klant.plaats", "klant.postcode_plaats", "klant.land", "klant.email",
    "klant.telefoon", "klant.adresblok",
    "bedrijf.naam", "bedrijf.adres", "bedrijf.postcode", "bedrijf.plaats", "bedrijf.land", "bedrijf.email", "bedrijf.telefoon",
    "bedrijf.website", "bedrijf.kvk", "bedrijf.btw_nummer", "bedrijf.iban", "bedrijf.bic", "bedrijf.tekst",
    "totaal_excl", "btw_totaal", "totaal", "btw_overzicht", "btw_labels", "btw_bedragen", "betaaltekst",
    "regel.nr", "regel.omschrijving", "regel.aantal", "regel.prijs", "regel.btw", "regel.bedrag_excl", "regel.bedrag_incl", "regel.totaal",
    "regel.optioneel",
)


class InvoiceError(Exception):
    """A template that cannot be used: `key` is a message key (server texts), `params` its placeholders."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key, self.params = key, params


# --- values -------------------------------------------------------------------------------------------------------

def money(value, lang: str) -> str:
    text = f"{Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP):,.2f}"
    if lang == "nl":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return f"€ {text}"


def day(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def invoice_language(business: dict) -> str:
    return business.get("invoice_language") if business.get("invoice_language") in LANGUAGES else DEFAULT_LANGUAGE


def _payment_days(business: dict) -> int:
    try:
        return max(0, int(business.get("payment_days", 14)))
    except (TypeError, ValueError):
        return 14


def vat_label(pct: str, lang: str) -> str:
    """"Btw hoog (21%)", "Btw laag (9%)" or "Btw 12%": the rates people know get their names."""
    key = {"21": "invoice.vat_high", "9": "invoice.vat_low"}.get(pct)
    return translate(lang, key, pct=pct) if key else translate(lang, "invoice.vat_row", pct=pct)


def epc_payload(business: dict, order: dict, amount) -> "str | None":
    """The text of a SEPA payment QR code (EPC069-12): banking apps read it and fill in the transfer. None without a usable IBAN and name."""
    if business.get("invoice_qr", True) is False:
        return None
    iban = re.sub(r"\s+", "", str(business.get("iban") or "")).upper()
    name = " ".join(str(business.get("name") or "").split())[:70]
    if not name or not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban) or Decimal(amount) <= 0:
        return None
    bic = re.sub(r"\s+", "", str(business.get("bic") or "")).upper()
    reference = str(order["invoice_number"] or "")[:140]
    return "\n".join(["BCD", "002", "1", "SCT", bic, name, iban, f"EUR{Decimal(amount).quantize(CENT)}", "", "", reference, ""])


LINK_FIELDS = ("bedrag", "bedrag_cent", "factuurnummer", "klantnummer", "betreft", "iban", "bestelnummer")
_LINK_TOKEN = re.compile(r"\{(\w+)\}")
MAX_LINK_LENGTH = 500


def link_template_problem(template: str) -> bool:
    """True when `template` cannot be used as a payment link: it must be an https address of limited length, and every {field} in it
    must be one that exists."""
    return not (template.startswith("https://") and len(template) <= MAX_LINK_LENGTH and not re.search(r"\s", template)
                and all(name in LINK_FIELDS for name in _LINK_TOKEN.findall(template))
                and not re.search(r"[{}]", _LINK_TOKEN.sub("", template)))                       # no stray brace left over


def payment_link(business: dict, order: dict, amount) -> "str | None":
    """The own payment link of the owner with this invoice filled in (every value made safe for an address), or None when there is
    none. Fields: bedrag (29.20), bedrag_cent (2920), factuurnummer, klantnummer, betreft, iban, bestelnummer."""
    template = str(business.get("invoice_qr_link") or "").strip()
    if not template or link_template_problem(template) or not order["invoice_number"]:
        return None
    total = Decimal(amount).quantize(CENT)
    values = {"bedrag": str(total), "bedrag_cent": str(int(total * 100)), "factuurnummer": order["invoice_number"],
              "klantnummer": order["customer_number"] or "", "betreft": order["subject"] or "",
              "iban": re.sub(r"\s+", "", str(business.get("iban") or "")).upper(), "bestelnummer": str(order["number"])}
    return _LINK_TOKEN.sub(lambda m: quote(values[m.group(1)], safe=""), template)


def qr_payload(business: dict, order: dict, amount) -> "str | None":
    """What the payment QR code holds: nothing when it is switched off, the owner's own payment link when there is one, else the SEPA
    transfer (see `epc_payload`)."""
    if business.get("invoice_qr", True) is False:
        return None
    return payment_link(business, order, amount) or epc_payload(business, order, amount)


def qr_png(payload: str) -> bytes:
    out = BytesIO()
    segno.make(payload, error="m", micro=False).save(out, kind="png", scale=6, border=2)
    return out.getvalue()


def build_mapping(order: dict, totals: dict, business: dict, lang: str) -> dict:
    """Every placeholder (except the line ones and the pictures) with its text."""
    b = {k: str(business.get(k) or "") for k in ("name", "address", "postal_code", "city", "country", "email", "phone", "website", "kvk",
                                                    "vat_id", "iban", "bic", "note")}
    due = order["invoice_date"] + timedelta(days=_payment_days(business)) if order["invoice_date"] else None
    place = " ".join(x for x in (order["postal_code"], order["city"]) if x)
    amount = money(totals["total"], lang)
    pay = translate(lang, "invoice.pay", amount=amount, due=day(due), number=order["invoice_number"] or "")
    vats = [row for row in totals["vat"] if Decimal(row["pct"]) > 0]
    return {
        "factuurnummer": order["invoice_number"] or "", "factuurdatum": day(order["invoice_date"]), "vervaldatum": day(due),
        "betreft": order["subject"] or translate(lang, "invoice.subject_default", n=order["number"]),
        "bestelnummer": str(order["number"]), "besteldatum": day(order["order_date"]), "leverdatum": day(order["delivery_date"]),
        "opmerking": order["notes"],
        "klant.naam": order["customer_name"], "klant.nummer": order["customer_number"], "klant.adres": order["address"],
        "klant.postcode": order["postal_code"], "klant.plaats": order["city"], "klant.postcode_plaats": place, "klant.land": order["country"],
        "klant.email": order["email"], "klant.telefoon": order["phone"],
        "klant.adresblok": "\n".join(x for x in (order["customer_name"], order["address"], place, order["country"]) if x),
        "bedrijf.naam": b["name"], "bedrijf.adres": b["address"], "bedrijf.postcode": b["postal_code"], "bedrijf.plaats": b["city"],
        "bedrijf.land": b["country"], "bedrijf.email": b["email"], "bedrijf.telefoon": b["phone"], "bedrijf.website": b["website"],
        "bedrijf.kvk": b["kvk"], "bedrijf.btw_nummer": b["vat_id"], "bedrijf.iban": b["iban"], "bedrijf.bic": b["bic"], "bedrijf.tekst": b["note"],
        "totaal_excl": money(totals["total_excl"], lang), "btw_totaal": money(totals["total_vat"], lang), "totaal": amount,
        "btw_overzicht": "\n".join(f"{vat_label(r['pct'], lang)}: {money(r['vat'], lang)}" for r in vats),
        "btw_labels": "\n".join(vat_label(r["pct"], lang) for r in vats), "btw_bedragen": "\n".join(money(r["vat"], lang) for r in vats),
        "betaaltekst": pay,
    }


def line_mappings(lines: list, totals: dict, lang: str) -> list:
    return [{"regel.nr": str(i), "regel.omschrijving": line["description"], "regel.aantal": str(line["quantity"]),
             "regel.prijs": money(line["unit_price"], lang), "regel.btw": f"{format(Decimal(line['vat_pct']).normalize(), 'f')}%",
             "regel.bedrag_excl": money(totals["line_net"][i - 1], lang), "regel.bedrag_incl": money(totals["line_totals"][i - 1], lang),
             "regel.totaal": money(totals["line_totals"][i - 1], lang),
             "regel.optioneel": translate(lang, "invoice.optional") if line.get("optional") else ""}
            for i, line in enumerate(lines, 1)]


def images_for(order: dict, totals: dict, business: dict, logo: "dict | None") -> dict:
    """The pictures an invoice can carry: the logo (as uploaded) and the payment QR (made for this invoice): {name: (bytes, kind)}."""
    out = {}
    if logo:
        out["logo"] = (logo["content"], logo["width_px"], logo["height_px"])
    payload = qr_payload(business, order, totals["total"])
    if payload:
        out["betaal_qr"] = (qr_png(payload), 0, 0)
    return out


# --- Word ---------------------------------------------------------------------------------------------------------

def _check_zip(content: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
                raise InvoiceError("invoice.err_too_big")
    except zipfile.BadZipFile:
        raise InvoiceError("invoice.err_docx") from None


def _open_docx(content: bytes):
    _check_zip(content)
    try:
        return Document(BytesIO(content))
    except Exception:                                   # not a Word file, or a damaged one: python-docx raises many things
        raise InvoiceError("invoice.err_docx") from None


def _roots(doc) -> list:
    roots = [doc.element.body]
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            if not part.is_linked_to_previous:          # reading `_element` of a linked one would create an empty header
                roots.append(part._element)
    return roots


def _row_text(tr) -> str:
    return "".join(t.text or "" for t in tr.iter(qn("w:t")))


def _line_rows(body) -> list:
    return [tr for tr in body.iter(qn("w:tr")) if "{{regel." in _row_text(tr).replace(" ", "")]


# Pictures in a Word file: the logo fits a box, the QR code is a square.
LOGO_BOX_CM = (5.0, 1.8)
QR_CM = 2.4


def _picture_size(token: str, image: tuple) -> tuple:
    if token == "betaal_qr":
        return Cm(QR_CM), Cm(QR_CM)
    _, width, height = image
    scale = min(LOGO_BOX_CM[0] / width, LOGO_BOX_CM[1] / height)
    return Cm(width * scale), Cm(height * scale)


def _fill(root, mapping: dict, images: "dict | None" = None, owner=None) -> None:
    """Replace the placeholders in every paragraph under `root`; one that is not known is left as it is, so a typo shows. A picture
    placeholder is taken out of the text and the picture is added at the end of its paragraph (only where `owner` can hold pictures)."""
    names = {**mapping, **{token: "" for token in IMAGE_TOKENS}}

    def sub(text: str) -> str:
        return PLACEHOLDER.sub(lambda m: names.get(m.group(1), m.group(0)), text)

    for p in root.iter(qn("w:p")):
        paragraph = Paragraph(p, owner)
        if "{{" not in paragraph.text:
            continue
        wanted = [m.group(1) for m in PLACEHOLDER.finditer(paragraph.text) if m.group(1) in IMAGE_TOKENS]
        for run in paragraph.runs:                      # the usual case: a placeholder sits inside one run, and keeps its look
            if "{{" in run.text:
                run.text = sub(run.text)
        known = [m for m in PLACEHOLDER.finditer(paragraph.text) if m.group(1) in names]
        if known and paragraph.runs:                    # Word split a placeholder over runs: join them, the first run's look wins
            whole = sub(paragraph.text)
            paragraph.runs[0].text = whole
            for run in paragraph.runs[1:]:
                run.text = ""
        for token in wanted:
            if images and token in images and owner is not None:
                width, height = _picture_size(token, images[token])
                paragraph.add_run().add_picture(BytesIO(images[token][0]), width=width, height=height)


def validate_docx(content: bytes) -> None:
    doc = _open_docx(content)
    if not _line_rows(doc.element.body):
        raise InvoiceError("invoice.err_no_row")


def render_docx(content: bytes, mapping: dict, lines: list, images: "dict | None" = None) -> bytes:
    doc = _open_docx(content)
    body = doc.element.body
    rows = _line_rows(body)
    if not rows:
        raise InvoiceError("invoice.err_no_row")
    owner = doc._body                                    # pictures are only added in the body: a header has a part of its own
    for row in rows:
        for values in lines:
            clone = copy.deepcopy(row)
            _fill(clone, {**mapping, **values}, images, owner)
            row.addprevious(clone)
        row.getparent().remove(row)
    for i, root in enumerate(_roots(doc)):
        _fill(root, mapping, images, owner if i == 0 else None)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


# The sample template: the layout of the example invoice, in Word. Open Sans like the example (Word substitutes another font where it is missing).
SAMPLE_FONT = "Open Sans"


def _run(paragraph, text, *, size=10, bold=False):
    run = paragraph.add_run(text)
    run.font.name = SAMPLE_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), SAMPLE_FONT)
    run.font.size = Pt(size)
    run.bold = bold
    return run


def _lines(cell_or_doc, items, *, align=None, space=0, before=0, indent=None):
    """Paragraphs [(text, size, bold), ...] in a cell (the first one reuses the cell's empty paragraph)."""
    first = True
    for text, size, bold in items:
        paragraph = cell_or_doc.paragraphs[0] if first and hasattr(cell_or_doc, "paragraphs") and cell_or_doc.paragraphs and not cell_or_doc.paragraphs[0].text else cell_or_doc.add_paragraph()
        first = False
        paragraph.paragraph_format.space_after = Pt(space)
        paragraph.paragraph_format.space_before = Pt(before)
        if indent is not None:
            paragraph.paragraph_format.left_indent = Cm(indent)
        if align is not None:
            paragraph.alignment = align
        _run(paragraph, text, size=size, bold=bold)


def _border(cell, *, bottom=None, top=None):
    """A thin black line under (or above) a cell: Word keeps cell borders in the cell's properties."""
    props = cell._tc.get_or_add_tcPr()
    borders = props.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        props.append(borders)
    for edge, on in (("top", top), ("bottom", bottom)):
        if on:
            element = OxmlElement(f"w:{edge}")
            for key, value in (("val", "single"), ("sz", "4"), ("space", "0"), ("color", "000000")):
                element.set(qn(f"w:{key}"), value)
            borders.append(element)


def _widths(table, widths_cm):
    table.autofit = False
    for column, width in zip(table.columns, widths_cm):        # the grid: Word and LibreOffice lay the columns out by it
        column.width = Cm(width)
    for row in table.rows:
        for cell, width in zip(row.cells, widths_cm):
            cell.width = Cm(width)


def sample_docx() -> bytes:
    """The standard Word template: the layout of the example invoice, with every field in it."""
    R, L = WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.LEFT
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(1.5)
    section.top_margin, section.bottom_margin = Cm(1.5), Cm(1.5)
    style = doc.styles["Normal"]
    style.font.name, style.font.size = SAMPLE_FONT, Pt(10)
    doc.paragraphs[0]._element.getparent().remove(doc.paragraphs[0]._element) if doc.paragraphs else None

    # logo and customer on the left, the company on the right
    head = doc.add_table(rows=1, cols=2)
    _widths(head, [8.4, 9.6])
    left_cell, right_cell = head.rows[0].cells
    left_cell.vertical_alignment = right_cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    _lines(left_cell, [("{{logo}}", 10, False)])
    _lines(left_cell, [("{{klant.naam}}", 12, True)], before=62, indent=1.5)
    _lines(left_cell, [("{{klant.adres}}", 12, False), ("{{klant.postcode_plaats}}", 12, False)], indent=1.5)
    _lines(right_cell, [("{{bedrijf.naam}}", 10.5, True), ("{{bedrijf.adres}}", 10.5, False),
                        ("{{bedrijf.postcode}} {{bedrijf.plaats}}", 10.5, False), ("", 6, False),
                        ("Btw-nummer: {{bedrijf.btw_nummer}}", 8, False), ("KVK-nummer: {{bedrijf.kvk}}", 8, False),
                        ("Tel.: {{bedrijf.telefoon}}", 8, False), ("E-mail: {{bedrijf.email}}", 8, False),
                        ("Website: {{bedrijf.website}}", 8, False), ("IBAN: {{bedrijf.iban}}", 8, False),
                        ("BIC: {{bedrijf.bic}}", 8, False)], align=R)
    doc.add_paragraph().paragraph_format.space_after = Pt(30)

    # invoice number and subject on the left, the dates on the right
    meta = doc.add_table(rows=1, cols=2)
    _widths(meta, [10.0, 8.0])
    left, right = meta.rows[0].cells
    left.vertical_alignment = WD_ALIGN_VERTICAL.BOTTOM
    _lines(left, [("Factuur: {{factuurnummer}}", 11.5, True)])
    _lines(right, [("Factuurdatum: {{factuurdatum}}", 10, False), ("Vervaldatum: {{vervaldatum}}", 10, False),
                   ("Klantnummer: {{klant.nummer}}", 10, False)], align=R)
    subject = doc.add_paragraph()
    subject.paragraph_format.space_before = Pt(4)
    _run(subject, "Betreft: {{betreft}}", size=10)
    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    # the lines: this table's second row is repeated for every line of the order
    table = doc.add_table(rows=2, cols=4)
    _widths(table, [1.4, 9.0, 3.4, 4.2])
    header, row = table.rows
    for cell, (text, align) in zip(header.cells, (("Aantal", L), ("Beschrijving", L), ("Bedrag\nexcl. btw", R), ("Bedrag\nincl. btw", R))):
        _lines(cell, [(text, 8, False)], align=align, space=3)
        _border(cell, bottom=True)
    _lines(row.cells[0], [("{{regel.aantal}}", 10, False)], align=L, before=5)
    _lines(row.cells[1], [("{{regel.omschrijving}}", 10, False)], align=L, before=5)
    _lines(row.cells[2], [("{{regel.bedrag_excl}}", 10, False)], align=R, before=5)
    _lines(row.cells[3], [("{{regel.bedrag_incl}}", 10, False), ("{{regel.btw}} Btw", 8, False)], align=R, before=5, space=4)
    for cell in row.cells:
        _border(cell, bottom=True)

    # the totals, right aligned
    totals = doc.add_table(rows=2, cols=3)
    _widths(totals, [4.8, 9.0, 4.2])
    top, last = totals.rows
    _lines(top.cells[1], [("Totaalbedrag excl. btw", 10, False), ("{{btw_labels}}", 10, False)], align=R, space=8, before=10)
    _lines(top.cells[2], [("{{totaal_excl}}", 10, False), ("{{btw_bedragen}}", 10, False)], align=R, space=8, before=10)
    _lines(last.cells[1], [("Totaalbedrag incl. btw", 10, True)], align=R, before=8, space=4)
    _lines(last.cells[2], [("{{totaal}}", 10, True)], align=R, before=8, space=4)
    for cell in last.cells:
        _border(cell, top=True)

    # payment
    pay = doc.add_paragraph()
    pay.paragraph_format.space_before = Pt(18)
    _run(pay, "{{betaaltekst}}", size=10)
    _run(doc.add_paragraph(), "{{betaal_qr}}", size=10)
    note = doc.add_paragraph()
    _run(note, "{{bedrijf.tekst}}", size=8)

    out = BytesIO()
    doc.save(out)
    return out.getvalue()


# --- PDF ----------------------------------------------------------------------------------------------------------

def validate_pdf(content: bytes) -> tuple:
    """The size of the first page in points; raises InvoiceError for anything that cannot be used as paper."""
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise InvoiceError("invoice.err_pdf_encrypted")
        page = reader.pages[0]
        return float(page.mediabox.width), float(page.mediabox.height)
    except InvoiceError:
        raise
    except Exception:
        raise InvoiceError("invoice.err_pdf") from None


_FONTS: dict = {}


def _fonts() -> tuple:
    """(regular, bold) font names: Open Sans from app/fonts; the standard Helvetica if the files are not there."""
    if not _FONTS:
        try:
            pdfmetrics.registerFont(TTFont("OpenSans", str(FONT_DIR / "OpenSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont("OpenSans-Bold", str(FONT_DIR / "OpenSans-Bold.ttf")))
            pdfmetrics.registerFontFamily("OpenSans", normal="OpenSans", bold="OpenSans-Bold", italic="OpenSans", boldItalic="OpenSans-Bold")
            _FONTS["names"] = ("OpenSans", "OpenSans-Bold")
        except Exception:
            _FONTS["names"] = ("Helvetica", "Helvetica-Bold")
    return _FONTS["names"]


def _p(text, style) -> PdfParagraph:
    return PdfParagraph(escape(str(text)).replace("\n", "<br/>"), style)


# Positions of the example invoice, in points from the top left of an A4 page.
LEFT = 43.0
CUSTOMER_X = 85.0
LOGO_BOX = (150.0, 50.0)
FIRST_FRAME_TOP = 278.0         # where the flowing part begins on the first page (the dates and the invoice number)
CUSTOMER_Y = 182.0              # baseline of the customer's name
NEXT_FRAME_TOP = 50.0


def _logo_size(logo: dict) -> tuple:
    scale = min(LOGO_BOX[0] / logo["width_px"], LOGO_BOX[1] / logo["height_px"])
    return logo["width_px"] * scale, logo["height_px"] * scale


def _draw_first_page(canvas, size, *, mapping, lang, logo, shift, with_company):
    """The fixed part of the first page: the logo, the company details on the right and the customer's address."""
    regular, bold = _fonts()
    width, height = size
    right = width - LEFT
    t = lambda key: translate(lang, key)         # noqa: E731
    if with_company:
        if logo:
            w, h = _logo_size(logo)
            canvas.drawImage(ImageReader(BytesIO(logo["content"])), LEFT, height - 45 - h, width=w, height=h, mask="auto")
        y = 53.5
        place = " ".join(x for x in (mapping["bedrijf.postcode"], mapping["bedrijf.plaats"]) if x)
        for text, font in ((mapping["bedrijf.naam"], bold), (mapping["bedrijf.adres"], regular), (place, regular), (mapping["bedrijf.land"], regular)):
            if text:
                canvas.setFont(font, 10.5)
                canvas.drawRightString(right, height - y, text)
                y += 14.0
        y = max(y, 81.5) + 13.0
        canvas.setFont(regular, 8)
        for label, key in (("invoice.vat_id_label", "bedrijf.btw_nummer"), ("invoice.kvk_label", "bedrijf.kvk"), ("invoice.tel_label", "bedrijf.telefoon"),
                           ("invoice.email_label", "bedrijf.email"), ("invoice.website_label", "bedrijf.website"), ("invoice.iban_label", "bedrijf.iban"),
                           ("invoice.bic_label", "bedrijf.bic")):
            if mapping[key]:
                canvas.drawRightString(right, height - y, f"{t(label)} {mapping[key]}")
                y += 13.7
    y = CUSTOMER_Y + shift
    for i, text in enumerate(x for x in (mapping["klant.naam"], mapping["klant.adres"], mapping["klant.postcode_plaats"], mapping["klant.land"]) if x):
        canvas.setFont(bold if i == 0 else regular, 12)
        canvas.drawString(CUSTOMER_X, height - y, text)
        y += 16.0


def _story(order, lines, totals, mapping, rows, lang, width, images):
    regular, bold = _fonts()
    t = lambda key, **kw: translate(lang, key, **kw)       # noqa: E731
    base = ParagraphStyle("base", fontName=regular, fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=11)
    right = ParagraphStyle("right", parent=base, alignment=2)
    right_small = ParagraphStyle("rs", parent=small, alignment=2)
    right_bold = ParagraphStyle("rb", parent=right, fontName=bold)
    bold_style = ParagraphStyle("bold", parent=base, fontName=bold, fontSize=11.5, leading=15)
    full = width - 2 * LEFT

    # the invoice number and subject on the left, the dates on the right
    meta = [f"{t('invoice.date')}: {mapping['factuurdatum']}", f"{t('invoice.due')}: {mapping['vervaldatum']}"]
    if mapping["klant.nummer"]:
        meta.append(f"{t('invoice.customer_number')}: {mapping['klant.nummer']}")
    left = [Spacer(1, 26), _p(f"{t('invoice.number_short')}: {mapping['factuurnummer']}", bold_style),
            PdfParagraph(f"{escape(t('invoice.subject'))}: {escape(mapping['betreft'])}", ParagraphStyle("subj", parent=base, spaceBefore=4))]
    head = Table([[left, [_p(line, right) for line in meta]]], colWidths=[full - 200, 200])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story = [head, Spacer(1, 14)]

    qty, excl, incl = 39.0, 80.0, 94.5
    data = [[_p(t("invoice.col_qty"), small), _p(t("invoice.col_desc"), small), _p(t("invoice.col_excl"), right_small), _p(t("invoice.col_incl"), right_small)]]
    headings = []
    for i, row in enumerate(rows):
        pct = row["regel.btw"]
        if row.get("heading"):
            headings.append(i + 1)
            data.append(["", _p(row["regel.omschrijving"], ParagraphStyle("heading", parent=base, fontName=bold)), "", ""])
            continue
        data.append([_p(row["regel.aantal"], base), _p(row["regel.omschrijving"], base), _p(row["regel.bedrag_excl"], right),
                     [_p(row["regel.bedrag_incl"], right), _p(t("invoice.vat_label", pct=pct.rstrip("%")), right_small)]])
    table = Table(data, colWidths=[qty, full - qty - excl - incl, excl, incl], repeatRows=1)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, 0), 0),
             ("BOTTOMPADDING", (0, 0), (-1, 0), 4), ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
             ("LINEBELOW", (0, -1), (-1, -1), 0.6, colors.black)]
    style += [("TOPPADDING", (0, i), (-1, i), 12) for i in headings]      # a little air above the heading of the optional lines
    table.setStyle(TableStyle(style))
    story.append(table)

    vats = [r for r in totals["vat"] if Decimal(r["pct"]) > 0]
    sums = []
    if vats:
        sums.append((t("invoice.total_excl"), mapping["totaal_excl"], False))
        sums += [(vat_label(r["pct"], lang), money(r["vat"], lang), False) for r in vats]
    sums.append((t("invoice.total") if vats else t("invoice.total_plain"), mapping["totaal"], True))
    # the labels end where the amount column of the lines ends, the amounts where the incl. column ends
    box = Table([["", _p(label, right_bold if strong else right), _p(value, right_bold if strong else right)] for label, value, strong in sums],
                colWidths=[full - incl - 200, 200, incl])
    box.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 7),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black)]))
    story += [box, Spacer(1, 36), _p(mapping["betaaltekst"], base)]
    if "betaal_qr" in images:
        story += [Spacer(1, 12), Image(BytesIO(images["betaal_qr"][0]), width=66, height=66, hAlign="LEFT")]
    if mapping["bedrijf.tekst"]:
        story += [Spacer(1, 10), _p(mapping["bedrijf.tekst"], small)]
    return story


def render_pdf(order, lines, totals, mapping, rows, business, lang, template: "dict | None", logo: "dict | None", images: dict) -> bytes:
    size = validate_pdf(template["content"]) if template else A4
    width, height = size
    if template:
        top = template["margin_top_mm"] * 72 / 25.4
        bottom = template["margin_bottom_mm"] * 72 / 25.4
        shift = (top + 12.0) - CUSTOMER_Y                       # the paper has its own header: start where the margin says
    else:
        bottom, shift = 42.0, 0.0
    if height - (FIRST_FRAME_TOP + shift) - bottom < 120 or shift + FIRST_FRAME_TOP < 0:
        raise InvoiceError("invoice.err_margins")
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=size, title=f"{translate(lang, 'invoice.title')} {mapping['factuurnummer']}", author=mapping["bedrijf.naam"],
                          leftMargin=LEFT, rightMargin=LEFT, topMargin=0, bottomMargin=bottom)
    first_top = FIRST_FRAME_TOP + shift
    first = Frame(LEFT, bottom, width - 2 * LEFT, height - first_top - bottom, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="first")
    later_top = max(NEXT_FRAME_TOP, top if template else 0)
    later = Frame(LEFT, bottom, width - 2 * LEFT, height - later_top - bottom, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="later")
    doc.addPageTemplates([
        PageTemplate("first", [first], onPage=lambda c, d: _draw_first_page(c, size, mapping=mapping, lang=lang, logo=logo, shift=shift, with_company=template is None)),
        PageTemplate("later", [later])])
    doc.build([NextPageTemplate("later"), *_story(order, lines, totals, mapping, rows, lang, width, images)])
    if not template:
        return buffer.getvalue()
    writer = PdfWriter()
    for page in PdfReader(BytesIO(buffer.getvalue())).pages:
        paper = PdfWriter(clone_from=BytesIO(template["content"])).pages[0]      # a fresh copy of the paper for every page
        paper.merge_page(page)
        writer.add_page(paper)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# --- one entry point ------------------------------------------------------------------------------------------------

def render_invoice(order: dict, lines: list, totals: dict, business: dict, template: "dict | None", logo: "dict | None" = None) -> tuple:
    """(file content, mimetype, extension)."""
    lang = invoice_language(business)
    mapping = build_mapping(order, totals, business, lang)
    rows = line_mappings(lines, totals, lang)
    images = images_for(order, totals, business, logo)
    # Optional lines (accessories) are listed apart: the built-in layout puts a heading above them; in a Word template, whose one row is
    # repeated for every line, each of them says "optioneel" itself (and `{{regel.optioneel}}` is there for a template that wants its own place).
    if template and template["kind"] == "docx":
        for row in rows:
            if row["regel.optioneel"]:
                row["regel.omschrijving"] = f"{row['regel.omschrijving']} ({row['regel.optioneel']})"
    else:
        first = next((i for i, row in enumerate(rows) if row["regel.optioneel"]), None)
        if first is not None:
            heading = {key: "" for key in rows[0]}
            heading["regel.omschrijving"] = translate(lang, "invoice.optional_heading")
            heading["heading"] = "1"
            rows.insert(first, heading)
    if template and template["kind"] == "docx":
        return (render_docx(template["content"], mapping, rows, images),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx")
    return render_pdf(order, lines, totals, mapping, rows, business, lang, template, logo, images), "application/pdf", "pdf"


# --- Word to PDF ----------------------------------------------------------------------------------------------------

CONVERT_TIMEOUT_S = 120


def docx_to_pdf(content: bytes) -> bytes:
    """The Word invoice as a PDF, made by LibreOffice (`SOFFICE_BIN`, default `soffice`; it is in the Docker image). Every call has its own
    profile folder, so two invoices made at the same moment do not trip over each other."""
    binary = shutil.which(os.environ.get("SOFFICE_BIN", "soffice"))
    if binary is None:
        raise InvoiceError("invoice.err_no_converter")
    with tempfile.TemporaryDirectory(prefix="invoice-") as work:
        source = Path(work) / "factuur.docx"
        source.write_bytes(content)
        command = [binary, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nofirststartwizard",
                   f"-env:UserInstallation={(Path(work) / 'profile').as_uri()}", "--convert-to", "pdf:writer_pdf_Export",
                   "--outdir", work, str(source)]
        try:
            subprocess.run(command, cwd=work, env={**os.environ, "HOME": work}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=CONVERT_TIMEOUT_S, check=True)
        except (subprocess.SubprocessError, OSError):
            raise InvoiceError("invoice.err_convert") from None
        result = Path(work) / "factuur.pdf"
        pdf = result.read_bytes() if result.is_file() else b""
    if not pdf.startswith(b"%PDF"):
        raise InvoiceError("invoice.err_convert")
    return pdf
