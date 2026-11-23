"""Order labels: a shipping label for one order, as a PDF with one label on it.

Two things are chosen, and both are a list that grows by one entry (never by a change of the code around it):

* a **sheet** (`FORMATS`): the paper the labels are printed on and where each label sits on it. Today one, an A4 sheet of sticker paper with two
  A5 labels; a sheet of four A6 labels, or a single A6, is one more `Sheet` here. The PDF is always a whole sheet with **one** label on it, in
  the place the person picks (`slot`, counted from 1 in the order the sheet lists them), so a half-used sheet can go through the printer again.
* a **layout** (`LAYOUTS`): what is drawn inside one label. A layout is a function that draws into the box it is given (`Box`, in points) and never
  knows which sheet it is on, so every layout works on every sheet, whatever the size of its labels.

A **label template** is a name for one such choice: `{id, name, format, layout}`. The templates are kept in the business's shared preferences
(`preferences.SHARED`, so the backup, restoring one and the factory reset carry them without a table of their own), validated here
(`validated_templates`, used by `api.validated_preferences`) and chosen on an order. The label says what the order says now: it is never kept.

The names of sheets, places and layouts are texts of the server (`label.format_<id>`, `label.slot_<id>_<n>`, `label.layout_<id>`), looked up
in the language of the request by `options`; `tests/test_labels.py` fails for an entry that has none.
"""
import uuid
from dataclasses import dataclass
from io import BytesIO

from flask import Blueprint, jsonify
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from . import invoice_docs
from .http import ApiError, login_required
from .i18n import request_language, translate

bp = Blueprint("labels", __name__, url_prefix="/api/labels")
MAX_TEMPLATES = 20
MAX_NAME = 60


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session."""


# --- the sheets ----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Sheet:
    """A sheet of label paper: its size and, in the order they are numbered, the labels on it, each as (x, y, width, height) in millimetres
    from the top left corner of the page."""
    id: str
    page_mm: tuple
    slots: tuple


@dataclass(frozen=True)
class Box:
    """Where a layout may draw: the label's rectangle in points, from the bottom left corner of the page (what reportlab counts in)."""
    x: float
    y: float
    width: float
    height: float


FORMATS = {sheet.id: sheet for sheet in (
    Sheet("a4_2xa5", (210, 297), ((0, 0, 210, 148.5), (0, 148.5, 210, 148.5))),      # A4, two A5 labels above one another
)}


def _box(sheet: Sheet, slot: int) -> Box:
    x, y, width, height = sheet.slots[slot - 1]
    return Box(x * mm, (sheet.page_mm[1] - y - height) * mm, width * mm, height * mm)


# --- what a label says ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LabelData:
    """Everything a layout needs, already in words: layouts never read an order, the preferences or the database."""
    lang: str
    sender: tuple               # the lines of the sender's address (the first is the name); empty when the business has none filled in
    recipient: tuple            # the lines of the customer's address (the first is the name)
    phone: str
    number: str                 # the order number
    customer_number: str
    subject: str
    logo: "dict | None"         # as `invoice_logo.load` gives it: content, width_px, height_px


def _place(postal_code, city) -> str:
    return " ".join(part for part in (postal_code, city) if part)


def _one_line(value) -> str:
    return " ".join(str(value or "").split())


def label_data(order: dict, business: dict, logo: "dict | None") -> LabelData:
    def lines(*values) -> tuple:
        return tuple(text for text in (_one_line(value) for value in values) if text)

    return LabelData(
        lang=invoice_docs.invoice_language(business),                        # the label follows the language of the invoice
        sender=lines(business.get("name"), business.get("address"), _place(business.get("postal_code"), business.get("city")), business.get("country")),
        recipient=lines(order["customer_name"], order["address"], _place(order["postal_code"], order["city"]), order["country"]),
        phone=_one_line(order["phone"]), number=str(order["number"]), customer_number=_one_line(order["customer_number"]),
        subject=_one_line(order["subject"]), logo=logo)


# --- fitting text into a box ---------------------------------------------------------------------------------------

LEADING = 1.22
GREY = colors.Color(0.38, 0.38, 0.38)


def _clip(text: str, font: str, size: float, width: float) -> str:
    """The text, cut with an ellipsis when it is wider than `width` (one word that is longer than the label is wide)."""
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(text: str, font: str, size: float, width: float, max_lines: "int | None" = None) -> list:
    lines = [_clip(line, font, size, width) for line in simpleSplit(text, font, size, width)] or [""]
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _clip(lines[-1].rstrip("…") + "…", font, size, width)
    return lines


def _fit(block: list, width: float, height: float, start: float, smallest: float) -> tuple:
    """(size, [(line, font)]) for the block, a list of (text, font): the largest size from `start` down to `smallest` at which it fits `height`
    once the long lines are wrapped. At `smallest` it is returned as it is, so an address that cannot fit is clipped, never drawn outside the label."""
    size = start
    while True:
        wrapped = [(line, font) for text, font in block for line in _wrap(text, font, size, width)]
        if len(wrapped) * size * LEADING <= height or size <= smallest:
            return size, wrapped
        size -= 0.5


def _draw_lines(canvas: Canvas, lines: list, size: float, x: float, top: float, *, align: str = "left") -> float:
    """Draw the lines one under the other, the first hanging from `top`; returns where the last one ends (every line is `size * LEADING` high)."""
    y = top
    for text, font in lines:
        canvas.setFont(font, size)
        (canvas.drawRightString if align == "right" else canvas.drawString)(x, y - size, text)
        y -= size * LEADING
    return y


# --- the layouts ---------------------------------------------------------------------------------------------------

LAYOUTS = {}


def layout(name: str):
    """Register a layout under `name`; it needs a text `label.layout_<name>` in both languages of the server."""
    def register(function):
        LAYOUTS[name] = function
        return function
    return register


LOGO_MAX = (46 * mm, 16 * mm)
CAPTION = 7                    # the small grey words "VAN" and "AAN"


@layout("verzendlabel")
def shipping_label(canvas: Canvas, box: Box, data: LabelData) -> None:
    """The customer's address large in the middle, the sender small at the top left (and the logo at the top right), and at the bottom what
    to find the order by: its number, the customer number and the subject."""
    regular, bold = invoice_docs._fonts()
    t = lambda key, **params: translate(data.lang, key, **params)       # noqa: E731
    pad, gap = 11 * mm, 7
    left, right = box.x + pad, box.x + box.width - pad
    top, bottom = box.y + box.height - pad, box.y + pad
    width = right - left

    def caption(key: str, y: float) -> float:
        canvas.setFillColor(GREY)
        below = _draw_lines(canvas, [(t(key).upper(), regular)], CAPTION, left, y)
        canvas.setFillColor(colors.black)
        return below

    def rule(y: float) -> None:
        canvas.setLineWidth(0.6)
        canvas.line(left, y, right, y)

    # the top: the sender on the left, the logo on the right, a rule under both
    header = 0.0
    if data.sender:
        sender = [(data.sender[0], bold)] + [(text, regular) for text in data.sender[1:]]
        size, lines = _fit(sender, width * 0.6, 62, 9.5, 7)
        header = top - _draw_lines(canvas, lines, size, left, caption("label.from", top))
    if data.logo:
        scale = min(LOGO_MAX[0] / data.logo["width_px"], LOGO_MAX[1] / data.logo["height_px"])
        w, h = data.logo["width_px"] * scale, data.logo["height_px"] * scale
        canvas.drawImage(ImageReader(BytesIO(data.logo["content"])), right - w, top - h, width=w, height=h, mask="auto")
        header = max(header, h)
    middle_top = top
    if header:
        rule(top - header - gap)
        middle_top = top - header - 2 * gap

    # the bottom: the number of the order and of the customer, with the subject under them, and a rule above
    facts = [t("label.order_number", n=data.number)] + ([t("label.customer_number", number=data.customer_number)] if data.customer_number else [])
    subject = _wrap(data.subject, regular, 9, width, max_lines=2) if data.subject else []
    footer = 11 * LEADING + len(subject) * 9 * LEADING
    y = bottom + footer
    _draw_lines(canvas, [(facts[0], bold)], 11, left, y)
    if len(facts) > 1:
        _draw_lines(canvas, [(facts[1], bold)], 11, right, y, align="right")
    _draw_lines(canvas, [(line, regular) for line in subject], 9, left, y - 11 * LEADING)
    rule(bottom + footer + gap)
    middle_bottom = bottom + footer + 2 * gap

    # the middle: who it goes to, as large as it fits, with the phone number under it for the courier; centred between the two rules
    if not data.recipient:
        return
    caption_h = CAPTION * LEADING + 3
    phone = t("label.phone", phone=data.phone) if data.phone else ""
    phone_h = 11 * LEADING + 6 if phone else 0
    block = [(data.recipient[0], bold)] + [(text, regular) for text in data.recipient[1:]]
    size, lines = _fit(block, width, max(middle_top - middle_bottom - caption_h - phone_h, 30), 28, 10)
    total = caption_h + len(lines) * size * LEADING + phone_h
    y = middle_top - max((middle_top - middle_bottom - total) / 2, 0)
    y = _draw_lines(canvas, lines, size, left, caption("label.to", y) - 3)
    if phone:
        _draw_lines(canvas, [(phone, regular)], 11, left, y - 6)


# --- making the PDF ------------------------------------------------------------------------------------------------

def render(order: dict, business: dict, logo: "dict | None", template: dict, slot: int) -> bytes:
    """One page the size of the template's sheet with the label of this order in place number `slot`; the rest of the sheet stays empty."""
    sheet, draw = FORMATS.get(template["format"]), LAYOUTS.get(template["layout"])
    if sheet is None or draw is None:                                       # a sheet or layout that a later release no longer has
        raise ApiError(404, "label.err_no_template")
    if not 1 <= slot <= len(sheet.slots):
        raise ApiError(400, "label.err_slot", max=len(sheet.slots))
    data = label_data(order, business, logo)
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(sheet.page_mm[0] * mm, sheet.page_mm[1] * mm), pageCompression=1)
    canvas.setTitle(translate(data.lang, "label.title", n=data.number))
    canvas.setAuthor(_one_line(business.get("name")))
    draw(canvas, _box(sheet, slot), data)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


# --- the templates -------------------------------------------------------------------------------------------------

def validated_templates(value) -> list:
    """The templates as they are stored: a list of `{id, name, format, layout}`, in the order given. A template that comes without an `id` is
    given one (the screens never invent one: `crypto.randomUUID` does not exist where the app is opened over plain http). Used by the
    settings and by restoring a backup, so both accept exactly the same things."""
    if not isinstance(value, list):
        raise ApiError(400, "label.err_templates")
    if len(value) > MAX_TEMPLATES:
        raise ApiError(400, "label.err_templates_max", max=MAX_TEMPLATES)
    out, seen = [], set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ApiError(400, "label.err_templates")
        name = raw.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name or len(name) > MAX_NAME:
            raise ApiError(400, "label.err_name", max=MAX_NAME)
        if raw.get("format") not in FORMATS:
            raise ApiError(400, "label.err_format")
        if raw.get("layout") not in LAYOUTS:
            raise ApiError(400, "label.err_layout")
        ident = raw.get("id")
        if ident in (None, ""):
            ident = str(uuid.uuid4())
        else:
            try:
                ident = str(uuid.UUID(str(ident)))
            except ValueError:
                raise ApiError(400, "label.err_id") from None
        if ident in seen:
            raise ApiError(400, "label.err_id")
        seen.add(ident)
        out.append({"id": ident, "name": name, "format": raw["format"], "layout": raw["layout"]})
    return out


def options(lang: str) -> dict:
    """What a template can be made of, with the names in `lang`: the screens draw their pull-downs from this and know no sheet or layout of their own."""
    return {
        "formats": [{"id": sheet.id, "name": translate(lang, f"label.format_{sheet.id}"),
                     "slots": [{"id": n, "name": translate(lang, f"label.slot_{sheet.id}_{n}")} for n in range(1, len(sheet.slots) + 1)]}
                    for sheet in FORMATS.values()],
        "layouts": [{"id": name, "name": translate(lang, f"label.layout_{name}")} for name in LAYOUTS],
        "max_templates": MAX_TEMPLATES, "max_name": MAX_NAME}


@bp.get("/options")
def get_options():
    return jsonify(options(request_language()))
