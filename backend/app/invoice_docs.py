"""Making the invoice file: from a Word template, from a PDF used as letter paper, or from the built-in layout.

A Word template holds `{{placeholders}}` (see PLACEHOLDERS); one table row that contains `{{regel.*}}` placeholders is the row
that is repeated for every order line. A PDF template is only the paper: the invoice is drawn on its first page (between the top
and bottom margins that were set with it), so a letterhead with logo and company details stays as it is. Without a template
the built-in layout is used, with the company details of the Settings at the top.

Everything uploaded is untrusted: size and unpacked size are capped, Word files go through python-docx (which does not resolve
XML entities) and PDFs are only read by pypdf, never executed.
"""
import copy
import re
import zipfile
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph as PdfParagraph
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

from .i18n import DEFAULT_LANGUAGE, LANGUAGES, translate

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024          # a Word file is a zip: what it unpacks to is capped as well
MAX_ZIP_ENTRIES = 2_000
CENT = Decimal("0.01")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)?)\s*\}\}")

# What can be put in a Word template. Shown in Settings and in the README; the sample template contains all of them.
PLACEHOLDERS = (
    "factuurnummer", "factuurdatum", "vervaldatum", "bestelnummer", "besteldatum", "leverdatum", "opmerking",
    "klant.naam", "klant.adres", "klant.postcode", "klant.plaats", "klant.postcode_plaats", "klant.land", "klant.email",
    "klant.telefoon", "klant.adresblok",
    "bedrijf.naam", "bedrijf.adres", "bedrijf.postcode", "bedrijf.plaats", "bedrijf.land", "bedrijf.email", "bedrijf.telefoon",
    "bedrijf.kvk", "bedrijf.btw_nummer", "bedrijf.iban", "bedrijf.tekst",
    "totaal_excl", "btw_totaal", "totaal", "btw_overzicht", "betaaltekst",
    "regel.nr", "regel.omschrijving", "regel.aantal", "regel.prijs", "regel.btw", "regel.totaal",
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
    return value.strftime("%d-%m-%Y") if value else ""


def invoice_language(business: dict) -> str:
    return business.get("invoice_language") if business.get("invoice_language") in LANGUAGES else DEFAULT_LANGUAGE


def _payment_days(business: dict) -> int:
    try:
        return max(0, int(business.get("payment_days", 14)))
    except (TypeError, ValueError):
        return 14


def build_mapping(order: dict, totals: dict, business: dict, lang: str) -> dict:
    """Every placeholder (except the line ones) with its text."""
    b = {k: str(business.get(k) or "") for k in ("name", "address", "postal_code", "city", "country", "email", "phone", "kvk",
                                                    "vat_id", "iban", "note")}
    due = order["invoice_date"] + timedelta(days=_payment_days(business)) if order["invoice_date"] else None
    place = " ".join(x for x in (order["postal_code"], order["city"]) if x)
    amount = money(totals["total"], lang)
    key = "invoice.pay" if b["iban"] else "invoice.pay_no_iban"
    pay = translate(lang, key, amount=amount, due=day(due), iban=b["iban"], number=order["invoice_number"] or "")
    vat_rows = [translate(lang, "invoice.vat_overview_row", pct=row["pct"], net=money(row["net"], lang), vat=money(row["vat"], lang))
                for row in totals["vat"] if Decimal(row["vat"]) > 0]
    return {
        "factuurnummer": order["invoice_number"] or "", "factuurdatum": day(order["invoice_date"]), "vervaldatum": day(due),
        "bestelnummer": str(order["number"]), "besteldatum": day(order["order_date"]), "leverdatum": day(order["delivery_date"]),
        "opmerking": order["notes"],
        "klant.naam": order["customer_name"], "klant.adres": order["address"], "klant.postcode": order["postal_code"],
        "klant.plaats": order["city"], "klant.postcode_plaats": place, "klant.land": order["country"], "klant.email": order["email"],
        "klant.telefoon": order["phone"],
        "klant.adresblok": "\n".join(x for x in (order["customer_name"], order["address"], place, order["country"]) if x),
        "bedrijf.naam": b["name"], "bedrijf.adres": b["address"], "bedrijf.postcode": b["postal_code"], "bedrijf.plaats": b["city"],
        "bedrijf.land": b["country"], "bedrijf.email": b["email"], "bedrijf.telefoon": b["phone"], "bedrijf.kvk": b["kvk"],
        "bedrijf.btw_nummer": b["vat_id"], "bedrijf.iban": b["iban"], "bedrijf.tekst": b["note"],
        "totaal_excl": money(totals["total_excl"], lang), "btw_totaal": money(totals["total_vat"], lang), "totaal": amount,
        "btw_overzicht": "\n".join(vat_rows), "betaaltekst": pay,
    }


def line_mappings(lines: list, totals: dict, lang: str) -> list:
    return [{"regel.nr": str(i), "regel.omschrijving": line["description"], "regel.aantal": str(line["quantity"]),
             "regel.prijs": money(line["unit_price"], lang),
             "regel.btw": f"{format(Decimal(line['vat_pct']).normalize(), 'f')}%", "regel.totaal": money(totals["line_totals"][i - 1], lang)}
            for i, line in enumerate(lines, 1)]


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


def _fill(root, mapping: dict) -> None:
    """Replace the placeholders in every paragraph under `root`; one that is not known is left as it is, so a typo shows."""
    def sub(text: str) -> str:
        return PLACEHOLDER.sub(lambda m: mapping.get(m.group(1), m.group(0)), text)

    for p in root.iter(qn("w:p")):
        paragraph = Paragraph(p, None)
        if "{{" not in paragraph.text:
            continue
        for run in paragraph.runs:                      # the usual case: a placeholder sits inside one run, and keeps its look
            if "{{" in run.text:
                run.text = sub(run.text)
        known = [m for m in PLACEHOLDER.finditer(paragraph.text) if m.group(1) in mapping]
        if known and paragraph.runs:                    # Word split a placeholder over runs: join them, the first run's look wins
            whole = sub(paragraph.text)
            paragraph.runs[0].text = whole
            for run in paragraph.runs[1:]:
                run.text = ""


def validate_docx(content: bytes) -> None:
    doc = _open_docx(content)
    if not _line_rows(doc.element.body):
        raise InvoiceError("invoice.err_no_row")


def render_docx(content: bytes, mapping: dict, lines: list) -> bytes:
    doc = _open_docx(content)
    body = doc.element.body
    rows = _line_rows(body)
    if not rows:
        raise InvoiceError("invoice.err_no_row")
    for row in rows:
        for values in lines:
            clone = copy.deepcopy(row)
            _fill(clone, {**mapping, **values})
            row.addprevious(clone)
        row.getparent().remove(row)
    for root in _roots(doc):
        _fill(root, mapping)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def sample_docx() -> bytes:
    """A starting point for a template: every placeholder in a plain layout."""
    doc = Document()
    doc.add_paragraph("{{bedrijf.naam}}").runs[0].bold = True
    doc.add_paragraph("{{bedrijf.adres}}\n{{bedrijf.postcode}} {{bedrijf.plaats}}\n{{bedrijf.email}} · {{bedrijf.telefoon}}")
    doc.add_paragraph("KvK {{bedrijf.kvk}} · Btw {{bedrijf.btw_nummer}} · IBAN {{bedrijf.iban}}")
    doc.add_heading("Factuur {{factuurnummer}}", level=1)
    doc.add_paragraph("{{klant.adresblok}}")
    doc.add_paragraph("Factuurdatum: {{factuurdatum}}\nVervaldatum: {{vervaldatum}}\nBestelling {{bestelnummer}} van {{besteldatum}}"
                      " · levering {{leverdatum}}")
    table = doc.add_table(rows=2, cols=5)
    table.style = "Table Grid"
    for cell, label in zip(table.rows[0].cells, ("Omschrijving", "Aantal", "Prijs", "Btw", "Totaal")):
        cell.text = label
    for cell, key in zip(table.rows[1].cells, ("omschrijving", "aantal", "prijs", "btw", "totaal")):
        cell.text = "{{regel.%s}}" % key                 # this row is repeated for every line of the order
    doc.add_paragraph("Totaal excl. btw: {{totaal_excl}}\n{{btw_overzicht}}\nTotaal incl. btw: {{totaal}}")
    doc.add_paragraph("{{betaaltekst}}")
    doc.add_paragraph("{{bedrijf.tekst}}")
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


def _styles():
    base = getSampleStyleSheet()["Normal"]
    base = ParagraphStyle("base", parent=base, fontName="Helvetica", fontSize=9.5, leading=13)
    return {"base": base, "bold": ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold"),
            "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=6),
            "right": ParagraphStyle("right", parent=base, alignment=2), "rightbold": ParagraphStyle("rb", parent=base, fontName="Helvetica-Bold", alignment=2),
            "small": ParagraphStyle("small", parent=base, fontSize=8.5, leading=11, textColor=colors.HexColor("#444444")),
            "company": ParagraphStyle("company", parent=base, fontName="Helvetica-Bold", fontSize=14, leading=17)}


def _p(text, style) -> PdfParagraph:
    return PdfParagraph(escape(str(text)).replace("\n", "<br/>"), style)


def _story(order, lines, totals, mapping, rows, business, lang, width, with_company: bool) -> list:
    s = _styles()
    t = lambda key, **kw: translate(lang, key, **kw)       # noqa: E731
    story = []
    if with_company:
        if mapping["bedrijf.naam"]:
            story.append(_p(mapping["bedrijf.naam"], s["company"]))
        place = " ".join(x for x in (mapping["bedrijf.postcode"], mapping["bedrijf.plaats"]) if x)
        details = [x for x in (mapping["bedrijf.adres"], place, mapping["bedrijf.land"], mapping["bedrijf.email"], mapping["bedrijf.telefoon"]) if x]
        ids = [x for x in (f"{t('invoice.kvk')} {mapping['bedrijf.kvk']}" if mapping["bedrijf.kvk"] else "",
                           f"{t('invoice.vat_id')} {mapping['bedrijf.btw_nummer']}" if mapping["bedrijf.btw_nummer"] else "",
                           f"IBAN {mapping['bedrijf.iban']}" if mapping["bedrijf.iban"] else "") if x]
        story += [_p("\n".join(details + ids), s["small"]), Spacer(1, 14 * mm)]
    story.append(_p(t("invoice.title"), s["title"]))
    meta = [(t("invoice.number"), mapping["factuurnummer"]), (t("invoice.date"), mapping["factuurdatum"]),
            (t("invoice.due"), mapping["vervaldatum"]),
            (t("invoice.order"), f"{mapping['bestelnummer']} · {mapping['besteldatum']}")]
    if mapping["leverdatum"]:
        meta.append((t("invoice.delivery"), mapping["leverdatum"]))
    left = _p(mapping["klant.adresblok"], s["base"])
    right = Table([[_p(label, s["small"]), _p(value, s["base"])] for label, value in meta], colWidths=[32 * mm, 45 * mm])
    right.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    head = Table([[left, right]], colWidths=[width - 80 * mm, 80 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 10 * mm)]

    data = [[_p("#", s["small"]), _p(t("invoice.col_desc"), s["small"]), _p(t("invoice.col_qty"), s["right"]),
             _p(t("invoice.col_price"), s["right"]), _p(t("invoice.col_vat"), s["right"]), _p(t("invoice.col_total"), s["right"])]]
    for row in rows:
        data.append([_p(row["regel.nr"], s["base"]), _p(row["regel.omschrijving"], s["base"]), _p(row["regel.aantal"], s["right"]),
                     _p(row["regel.prijs"], s["right"]), _p(row["regel.btw"], s["right"]), _p(row["regel.totaal"], s["right"])])
    fixed = [8 * mm, 14 * mm, 25 * mm, 14 * mm, 26 * mm]
    table = Table(data, colWidths=[fixed[0], width - sum(fixed), *fixed[1:]], repeatRows=1)
    table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black), ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [table, Spacer(1, 5 * mm)]

    sums = []
    if Decimal(totals["total_vat"]) > 0:
        sums.append((t("invoice.total_excl"), mapping["totaal_excl"], "base"))
        sums += [(t("invoice.vat_row", pct=r["pct"]), money(r["vat"], lang), "base") for r in totals["vat"] if Decimal(r["vat"]) > 0]
    sums.append((t("invoice.total"), mapping["totaal"], "bold"))
    box = Table([[_p(label, s[style]), _p(value, s["rightbold" if style == "bold" else "right"])] for label, value, style in sums],
                colWidths=[55 * mm, 30 * mm], hAlign="RIGHT")
    box.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [box, Spacer(1, 8 * mm), _p(mapping["betaaltekst"], s["base"])]
    if mapping["bedrijf.tekst"]:
        story += [Spacer(1, 4 * mm), _p(mapping["bedrijf.tekst"], s["small"])]
    return story


def render_pdf(order, lines, totals, mapping, rows, business, lang, template: "dict | None") -> bytes:
    size = validate_pdf(template["content"]) if template else A4
    top = (template["margin_top_mm"] if template else 20) * mm
    bottom = (template["margin_bottom_mm"] if template else 20) * mm
    side = 20 * mm
    if top + bottom >= size[1] - 40 * mm:
        raise InvoiceError("invoice.err_margins")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=size, leftMargin=side, rightMargin=side, topMargin=top, bottomMargin=bottom,
                            title=f"{translate(lang, 'invoice.title')} {mapping['factuurnummer']}", author=mapping["bedrijf.naam"])
    doc.build(_story(order, lines, totals, mapping, rows, business, lang, size[0] - 2 * side, with_company=template is None))
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

def render_invoice(order: dict, lines: list, totals: dict, business: dict, template: "dict | None") -> tuple:
    """(file content, mimetype, extension)."""
    lang = invoice_language(business)
    mapping = build_mapping(order, totals, business, lang)
    rows = line_mappings(lines, totals, lang)
    if template and template["kind"] == "docx":
        return (render_docx(template["content"], mapping, rows),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx")
    return render_pdf(order, lines, totals, mapping, rows, business, lang, template), "application/pdf", "pdf"
