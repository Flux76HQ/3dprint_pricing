"""Order labels: the sheets and layouts that can be chosen, the templates an administrator makes of them, and the PDF of one order's label."""
import io
import re
from itertools import combinations

import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

from app import i18n, labels
from tests.test_auth_api import H, post
from tests.test_domain_api import owner                      # noqa: F401  (fixture)
from tests.test_orders import business, new_order, pdf_images, picture, upload_logo
from tests.test_users import join_with_passkey

A4 = (210 * mm, 297 * mm)
TEMPLATE = {"name": "Verzendlabel A5", "format": "a4_2xa5", "layout": "verzendlabel"}


def templates(owner, *items):
    """Save these as the label templates (without ids, as the screen does) and return them as stored, with their ids."""
    res = owner.put("/api/preferences", json={"label_templates": list(items) or [TEMPLATE]}, headers=H)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["label_templates"]


def label(owner, order, template, slot=None, **headers):
    query = f"template={template['id']}" + (f"&slot={slot}" if slot is not None else "")
    return owner.get(f"/api/orders/{order['id']}/label?{query}", headers=headers)


def texts(pdf: bytes) -> list:
    """[(x, y, text)] of everything written on the first page, in points from the bottom left corner."""
    found = []

    def visit(text, cm, tm, _font, _size):
        if text.strip():
            found.append((tm[4] * cm[0] + tm[5] * cm[2] + cm[4], tm[4] * cm[1] + tm[5] * cm[3] + cm[5], text.strip()))
    PdfReader(io.BytesIO(pdf)).pages[0].extract_text(visitor_text=visit)
    return found


def extents(pdf: bytes) -> list:
    """[(x, y, right edge, text)] of everything written on the first page: where each piece starts and where it ends (its width in the font it is set in)."""
    regular, bold = labels.invoice_docs._fonts()
    found = []

    def visit(text, cm, tm, font, size):
        if text.strip():
            name = bold if "Bold" in str((font or {}).get("/BaseFont", "")) else regular
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            found.append((x, tm[4] * cm[1] + tm[5] * cm[3] + cm[5], x + stringWidth(text.rstrip("\n"), name, size * (tm[0] or 1)), text.strip()))
    PdfReader(io.BytesIO(pdf)).pages[0].extract_text(visitor_text=visit)
    return found


# --- what can be chosen ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_every_sheet_place_and_layout_has_a_name_in_every_language(lang):
    """A new sheet or layout is one entry in `labels.py` and its texts; without the texts the pull-down would show a key."""
    found = labels.options(lang)
    names = [sheet["name"] for sheet in found["formats"]] + [slot["name"] for sheet in found["formats"] for slot in sheet["slots"]] \
        + [layout["name"] for layout in found["layouts"]] + [field["name"] for field in found["fields"]]
    assert names and not [name for name in names if name.startswith("label.")], names
    assert [sheet["id"] for sheet in found["formats"]] == list(labels.FORMATS) and [layout["id"] for layout in found["layouts"]] == list(labels.LAYOUTS)
    assert [field["id"] for field in found["fields"]] == list(labels.FIELDS)


@pytest.mark.parametrize("sheet", labels.FORMATS.values(), ids=list(labels.FORMATS))
def test_the_places_of_a_sheet_lie_on_the_page_and_not_on_each_other(sheet):
    width, height = sheet.page_mm
    assert sheet.slots
    for x, y, w, h in sheet.slots:
        assert x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height, (x, y, w, h)
    for (ax, ay, aw, ah), (bx, by, bw, bh) in combinations(sheet.slots, 2):
        assert ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay, "two labels on one another"


def test_the_sheet_of_today_is_an_a4_with_two_a5_labels_above_one_another():
    sheet = labels.FORMATS["a4_2xa5"]
    assert sheet.page_mm == (210, 297) and sheet.slots == ((0, 0, 210, 148.5), (0, 148.5, 210, 148.5))


CHOICES = {"all on": {}, "all off": {field: False for field in labels.FIELDS},
           **{f"only {field}": {other: other == field for other in labels.FIELDS} for field in labels.FIELDS}}


@pytest.mark.parametrize("sheet", labels.FORMATS.values(), ids=list(labels.FORMATS))
@pytest.mark.parametrize("layout", labels.LAYOUTS)
@pytest.mark.parametrize("fields", CHOICES.values(), ids=list(CHOICES))
def test_every_layout_stays_inside_its_label_on_every_sheet_however_long_the_address_is(sheet, layout, fields):
    """A layout is drawn into the box it is given and never knows the sheet: a long name, address and subject are wrapped, made smaller and in the end
    cut, never drawn over the next label or off the paper."""
    long = "Stichting Vrienden van het Historisch Museum en Archief Utrecht-Oost " * 3
    order = {"number": 7, "customer_name": long, "customer_number": "K" * 30, "address": long, "postal_code": "1234 AB", "city": long, "country": long,
             "phone": "06 12345678", "subject": long, "email": "", "notes": ""}
    shop = {"name": long, "address": long, "postal_code": "3500 AA", "city": long, "country": long}
    for slot in range(1, len(sheet.slots) + 1):
        logo = {"content": picture(), "width_px": 600, "height_px": 200}
        pdf = labels.render(order, shop, logo, {"format": sheet.id, "layout": layout, "fields": fields}, slot)
        box = labels._box(sheet, slot)
        written = extents(pdf)
        assert written
        for x, y, end, text in written:
            assert box.x <= x and end <= box.x + box.width + 0.5 and box.y <= y <= box.y + box.height, (slot, text, x, end, y)


def test_a_long_line_is_cut_with_an_ellipsis_and_a_long_text_is_wrapped():
    regular, _ = labels.invoice_docs._fonts()
    clipped = labels._clip("Doorgaanwegmetdeheleverrelangestraatnaamenhuisnummer", regular, 20, 100)
    assert clipped.endswith("…") and stringWidth(clipped, regular, 20) <= 100
    assert labels._clip("Kort", regular, 20, 100) == "Kort"
    lines = labels._wrap("een tekst die over meerdere regels loopt en nog veel langer is dan dat", regular, 10, 120, max_lines=2)
    assert len(lines) == 2 and lines[-1].endswith("…") and all(stringWidth(line, regular, 10) <= 120 for line in lines)


# --- the templates -----------------------------------------------------------------------------------------------

def test_templates_are_kept_with_an_id_and_the_screen_does_not_have_to_make_one(owner):
    (first, second) = templates(owner, TEMPLATE, {**TEMPLATE, "name": "  Tweede  ", "colour": "red"})
    assert first["name"] == "Verzendlabel A5" and second["name"] == "Tweede" and first["id"] != second["id"]
    assert set(first) == {"id", "name", "format", "layout", "fields"} and set(second) == set(first)    # what is not a template's is dropped
    assert first["fields"] == {field: True for field in labels.FIELDS}                                 # nothing said: everything is printed
    assert owner.get("/api/preferences").get_json()["label_templates"] == [first, second]
    again = owner.put("/api/preferences", json={"label_templates": [second, first]}, headers=H).get_json()["label_templates"]
    assert again == [second, first]                                                                     # the ids stay, the order is the one given
    assert owner.put("/api/preferences", json={"theme": "dark"}, headers=H).get_json()["label_templates"] == [second, first]    # other changes leave them alone
    assert owner.put("/api/preferences", json={"label_templates": []}, headers=H).get_json()["label_templates"] == []


@pytest.mark.parametrize("bad", [
    "een sjabloon", {"name": "x"}, ["tekst"], [None],
    [{**TEMPLATE, "name": ""}], [{**TEMPLATE, "name": "   "}], [{**TEMPLATE, "name": "x" * (labels.MAX_NAME + 1)}], [{**TEMPLATE, "name": 5}], [{k: v for k, v in TEMPLATE.items() if k != "name"}],
    [{**TEMPLATE, "format": "a3"}], [{**TEMPLATE, "format": ""}], [{k: v for k, v in TEMPLATE.items() if k != "format"}],
    [{**TEMPLATE, "layout": "fraai"}], [{**TEMPLATE, "layout": None}],
    [{**TEMPLATE, "id": "geen-uuid"}], [{**TEMPLATE, "id": 12}],
    [{**TEMPLATE, "fields": "alles"}], [{**TEMPLATE, "fields": None}], [{**TEMPLATE, "fields": ["sender"]}], [{**TEMPLATE, "fields": {"kleur": True}}],
    [{**TEMPLATE, "fields": {"sender": "ja"}}], [{**TEMPLATE, "fields": {"sender": 0}}], [{**TEMPLATE, "fields": {"sender": None}}],
    [{**TEMPLATE, "id": "11111111-1111-4111-8111-111111111111"}, {**TEMPLATE, "id": "11111111-1111-4111-8111-111111111111"}],
    [TEMPLATE] * (labels.MAX_TEMPLATES + 1),
])
def test_a_template_that_makes_no_sense_is_refused_and_nothing_is_kept(owner, bad):
    kept = templates(owner)
    res = owner.put("/api/preferences", json={"label_templates": bad}, headers=H)
    assert res.status_code == 400 and res.get_json()["error"], bad
    assert owner.get("/api/preferences").get_json()["label_templates"] == kept


def test_the_most_templates_that_are_allowed_can_be_kept(owner):
    assert len(templates(owner, *[TEMPLATE] * labels.MAX_TEMPLATES)) == labels.MAX_TEMPLATES


def test_the_refusal_is_in_the_language_asked_for(owner):
    body = {"label_templates": [{**TEMPLATE, "format": "a3"}]}
    assert owner.put("/api/preferences", json=body, headers={**H, "X-Lang": "en"}).get_json()["error"] == "Unknown sheet format for a label template."
    assert owner.put("/api/preferences", json=body, headers={**H, "X-Lang": "nl"}).get_json()["error"] == "Onbekend vel-formaat voor een labelsjabloon."


def test_only_an_administrator_changes_the_templates_and_everybody_sees_and_uses_them(owner, app):
    (kept,) = templates(owner)
    order = new_order(owner)
    anna = join_with_passkey(app, owner, "Anna")
    res = anna.put("/api/preferences", json={"label_templates": []}, headers=H)
    assert res.status_code == 403
    assert anna.get("/api/preferences").get_json()["label_templates"] == [kept]
    assert label(anna, order, kept, 1).status_code == 200
    options = anna.get("/api/labels/options").get_json()
    assert [sheet["id"] for sheet in options["formats"]] == ["a4_2xa5"] and options["max_templates"] == labels.MAX_TEMPLATES


def test_the_options_come_in_the_language_asked_for(owner):
    nl = owner.get("/api/labels/options", headers={"X-Lang": "nl"}).get_json()
    en = owner.get("/api/labels/options", headers={"X-Lang": "en"}).get_json()
    assert nl["formats"][0]["slots"] == [{"id": 1, "name": "Boven (label 1)"}, {"id": 2, "name": "Onder (label 2)"}]
    assert en["formats"][0]["slots"] == [{"id": 1, "name": "Top (label 1)"}, {"id": 2, "name": "Bottom (label 2)"}]
    assert nl["layouts"] == [{"id": "verzendlabel", "name": "Verzendlabel"}] and en["layouts"] == [{"id": "verzendlabel", "name": "Shipping label"}]


def test_the_label_routes_need_a_session(client):
    assert client.get("/api/labels/options", headers=H).status_code == 401
    assert client.get("/api/orders/" + "0" * 8 + "-0000-0000-0000-" + "0" * 12 + "/label?template=x", headers=H).status_code == 401


# --- the label itself --------------------------------------------------------------------------------------------

def test_the_label_is_one_a4_page_with_one_label_on_the_place_asked_for(owner):
    business(owner)
    (template,) = templates(owner)
    order = new_order(owner, subject="Rack-houders voor oktober")
    page_height = A4[1]
    half = page_height / 2
    for slot, upper in ((None, True), (1, True), (2, False)):
        res = label(owner, order, template, slot)
        assert res.status_code == 200 and res.mimetype == "application/pdf" and res.data.startswith(b"%PDF")
        assert res.headers["Content-Disposition"] == f'attachment; filename="Label-{order["number"]}.pdf"'
        reader = PdfReader(io.BytesIO(res.data))
        assert len(reader.pages) == 1 and abs(float(reader.pages[0].mediabox.width) - A4[0]) < 0.5 and abs(float(reader.pages[0].mediabox.height) - page_height) < 0.5
        written = texts(res.data)
        assert written and all((y > half) == upper for _, y, _ in written), (slot, written)            # the other half of the sheet stays empty
        everything = " ".join(text for _, _, text in written)
        for word in ("Jan Jansen", "Kerkstraat 1", "1234 AB Utrecht", "Nederland", "Flux76 Prints", "Industrieweg 5", "3500 AA Utrecht",
                     f"Bestelling {order['number']}", "Klantnummer K9999", "Rack-houders voor oktober"):
            assert word in everything, (word, everything)


def test_the_label_says_what_the_order_says_now_and_is_not_kept(owner):
    business(owner)
    (template,) = templates(owner)
    order = new_order(owner, subject="Eerst")
    assert "Eerst" in " ".join(t for _, _, t in texts(label(owner, order, template).data))
    owner.put(f"/api/orders/{order['id']}", json={**order, "subject": "Daarna"}, headers=H)
    now = " ".join(t for _, _, t in texts(label(owner, order, template).data))
    assert "Daarna" in now and "Eerst" not in now


def test_the_label_follows_the_language_of_the_invoice(owner):
    (template,) = templates(owner)
    order = new_order(owner)
    business(owner, invoice_language="en")
    english = " ".join(t for _, _, t in texts(label(owner, order, template).data))
    assert "FROM" in english and "TO" in english and f"Order {order['number']}" in english and "Customer number K9999" in english
    business(owner, invoice_language="nl")
    dutch = " ".join(t for _, _, t in texts(label(owner, order, template).data))
    assert "VAN" in dutch and "AAN" in dutch and f"Bestelling {order['number']}" in dutch


def test_without_company_details_there_is_no_sender_but_there_is_a_label(owner):
    (template,) = templates(owner)
    order = new_order(owner)
    written = " ".join(t for _, _, t in texts(label(owner, order, template).data))
    assert "VAN" not in written and "Jan Jansen" in written


def test_the_logo_is_on_the_label_when_there_is_one(owner):
    business(owner)
    (template,) = templates(owner)
    order = new_order(owner)
    assert pdf_images(label(owner, order, template).data) == 0
    assert upload_logo(owner, "logo.png", picture()).status_code == 201
    assert pdf_images(label(owner, order, template).data) == 1


def test_an_order_without_lines_still_gets_a_label(owner):
    (template,) = templates(owner)
    assert label(owner, new_order(owner, []), template).status_code == 200


@pytest.mark.parametrize("slot", ["0", "3", "-1", "x", "1.5", ""])
def test_a_place_that_is_not_on_the_sheet_is_refused_with_the_number_of_places(owner, slot):
    (template,) = templates(owner)
    res = owner.get(f"/api/orders/{new_order(owner)['id']}/label?template={template['id']}&slot={slot}", headers={**H, "X-Lang": "en"})
    assert res.status_code == 400 and res.get_json()["error"] == "That position is not on the sheet: choose a position from 1 to 2."


def test_an_unknown_template_or_order_is_not_found(owner):
    (template,) = templates(owner)
    order = new_order(owner)
    assert owner.get(f"/api/orders/{order['id']}/label", headers=H).status_code == 404                       # no template named
    assert owner.get(f"/api/orders/{order['id']}/label?template=11111111-1111-4111-8111-111111111111", headers=H).status_code == 404
    assert owner.get(f"/api/orders/{order['id']}/label?template=niet-een-id", headers=H).status_code == 404
    assert owner.get(f"/api/orders/11111111-1111-4111-8111-111111111111/label?template={template['id']}", headers=H).status_code == 404
    assert label(owner, order, {"id": template["id"].upper()}).status_code == 200                              # the id is the same however it is written


def test_a_template_of_a_sheet_or_layout_a_later_release_no_longer_has_is_not_found(owner, monkeypatch):
    (template,) = templates(owner)
    order = new_order(owner)
    monkeypatch.delitem(labels.FORMATS, "a4_2xa5")
    assert label(owner, order, template).status_code == 404
    monkeypatch.undo()
    monkeypatch.delitem(labels.LAYOUTS, "verzendlabel")
    assert label(owner, order, template).status_code == 404


def test_a_new_sheet_and_a_new_layout_are_one_entry_each(owner, monkeypatch):
    """The point of the registries: another sheet (four A6 labels) and another layout work without a change anywhere else."""
    business(owner)
    monkeypatch.setitem(labels.FORMATS, "a4_4xa6", labels.Sheet("a4_4xa6", (210, 297), ((0, 0, 105, 148.5), (105, 0, 105, 148.5), (0, 148.5, 105, 148.5), (105, 148.5, 105, 148.5))))

    @labels.layout("alleen_naam")
    def only_the_name(canvas, box, data):
        canvas.drawString(box.x + 10, box.y + box.height - 20, data.recipient[0])
    monkeypatch.setitem(i18n._CATALOGS["nl"], "label.format_a4_4xa6", "A4 met 4 labels (A6)")
    monkeypatch.setitem(i18n._CATALOGS["nl"], "label.slot_a4_4xa6_3", "Linksonder")
    monkeypatch.setitem(i18n._CATALOGS["nl"], "label.layout_alleen_naam", "Alleen de naam")
    try:
        (template,) = templates(owner, {"name": "Klein", "format": "a4_4xa6", "layout": "alleen_naam"})
        order = new_order(owner)
        (x, y, text) = texts(label(owner, order, template, 3).data)[0]
        assert text == "Jan Jansen" and x < A4[0] / 2 and y < A4[1] / 2                                  # the third place: bottom left
        assert label(owner, order, template, 5).status_code == 400
        options = owner.get("/api/labels/options", headers={"X-Lang": "nl"}).get_json()
        assert [f["id"] for f in options["formats"]] == ["a4_2xa5", "a4_4xa6"] and options["formats"][1]["slots"][2]["name"] == "Linksonder"
    finally:
        labels.LAYOUTS.pop("alleen_naam", None)


# --- the fields ------------------------------------------------------------------------------------------------

MARKERS = {"sender": "Flux76 Prints", "country": "Nederland", "phone": "Tel. 06 12345678", "order_number": "Bestelling ", "customer_number": "Klantnummer ",
           "subject": "Rack-houders voor oktober", "logo": None}                  # the logo is a picture: it is counted, not read


def everything(owner, **fields):
    """An order with everything filled in, its label with these fields on or off (the rest on), and the text and the number of pictures on it."""
    business(owner)
    upload_logo(owner, "logo.png", picture())
    (template,) = templates(owner, {**TEMPLATE, "fields": fields})
    order = new_order(owner, subject="Rack-houders voor oktober", phone="06 12345678")
    pdf = label(owner, order, template).data
    return " ".join(text for _, _, text in texts(pdf)), pdf_images(pdf)


def test_every_field_is_there_when_it_is_on_and_gone_when_it_is_off_and_the_rest_stays(owner):
    """A field in `FIELDS` that `label_data` does not honour would be a switch that does nothing: each one is switched off alone."""
    assert set(MARKERS) == set(labels.FIELDS), "a new field needs a marker here"
    full, pictures = everything(owner)
    assert pictures == 1 and all(marker in full for marker in MARKERS.values() if marker)
    for field, marker in MARKERS.items():
        written, pictures = everything(owner, **{field: False})
        if marker:
            assert marker not in written, field
            assert pictures == 1
        else:
            assert pictures == 0, field
        for other, other_marker in MARKERS.items():
            if other != field and other_marker:
                assert other_marker in written, (field, other)                                  # the rest is untouched
        assert "Jan Jansen" in written and "Kerkstraat 1" in written and "1234 AB Utrecht" in written      # the customer's address is always there


def test_with_everything_off_the_label_holds_only_the_address_of_the_recipient_in_the_middle(owner):
    written, pictures = everything(owner, **{field: False for field in labels.FIELDS})
    assert pictures == 0
    assert written == "AAN Jan Jansen Kerkstraat 1 1234 AB Utrecht"
    (template,) = templates(owner, {**TEMPLATE, "fields": {field: False for field in labels.FIELDS}})
    pdf = label(owner, new_order(owner), template).data
    found = texts(pdf)
    box = labels._box(labels.FORMATS["a4_2xa5"], 1)
    middle = (max(y for _, y, _ in found) + min(y for _, y, _ in found)) / 2
    assert abs(middle - (box.y + box.height / 2)) < 3, (middle, box)                                 # centred on the label: no gap is kept for what is not there
    assert not re.search(rb"\sl\s", PdfReader(io.BytesIO(pdf)).pages[0].get_contents().get_data())      # and no rule: there is nothing above or below to separate it from
    full = label(owner, new_order(owner), templates(owner)[0]).data
    assert len(re.findall(rb"\sl\s", PdfReader(io.BytesIO(full)).pages[0].get_contents().get_data())) == 2        # (with everything on there are two)


def test_the_sender_can_be_left_off_while_the_logo_stays_and_the_other_way_round(owner):
    written, pictures = everything(owner, sender=False)
    assert "Flux76 Prints" not in written and "VAN" not in written and pictures == 1
    written, pictures = everything(owner, logo=False)
    assert "Flux76 Prints" in written and "VAN" in written and pictures == 0


def test_a_template_from_before_the_fields_prints_everything(owner, app):
    """A template stored by the release that had no fields has no `fields`: it prints what it always did."""
    from tests.conftest import connect
    business(owner)
    (template,) = templates(owner)
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        import json
        row = conn.execute("SELECT preferences FROM shared_preferences").fetchone()[0]                    # already a dict
        row["label_templates"] = [{k: v for k, v in row["label_templates"][0].items() if k != "fields"}]
        conn.execute("UPDATE shared_preferences SET preferences = %s", (json.dumps(row),))
    assert "fields" not in owner.get("/api/preferences").get_json()["label_templates"][0]
    written = " ".join(text for _, _, text in texts(label(owner, new_order(owner, subject="Eerst"), template).data))
    assert "Flux76 Prints" in written and "Eerst" in written and "Klantnummer" in written


def test_the_fields_are_in_the_options_in_the_language_asked_for(owner):
    en = owner.get("/api/labels/options", headers={"X-Lang": "en"}).get_json()["fields"]
    nl = owner.get("/api/labels/options", headers={"X-Lang": "nl"}).get_json()["fields"]
    assert [f["id"] for f in en] == list(labels.FIELDS) == [f["id"] for f in nl]
    assert {f["id"]: f["name"] for f in nl}["sender"] == "Afzendadres (je bedrijfsgegevens)" and {f["id"]: f["name"] for f in en}["sender"] == "Sender address (your business details)"


# --- backup ----------------------------------------------------------------------------------------------------

def test_the_templates_are_in_a_backup_and_come_back_with_it(owner):
    kept = templates(owner, TEMPLATE, {**TEMPLATE, "name": "Tweede", "fields": {"sender": False, "phone": False}})
    assert kept[1]["fields"]["sender"] is False and kept[1]["fields"]["subject"] is True
    doc = owner.get("/api/backup", headers=H).get_json()
    assert doc["preferences"]["label_templates"] == kept
    owner.put("/api/preferences", json={"label_templates": []}, headers=H)
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert owner.get("/api/preferences").get_json()["label_templates"] == kept
    order = new_order(owner)
    assert label(owner, order, kept[1], 2).status_code == 200                                              # the same ids, so a remembered choice still works


def test_a_backup_from_before_the_templates_restores_and_a_broken_one_is_refused(owner):
    doc = owner.get("/api/backup", headers=H).get_json()
    assert "label_templates" not in doc["preferences"]
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert "label_templates" not in owner.get("/api/preferences").get_json()
    kept = templates(owner)
    doc["preferences"]["label_templates"] = [{**TEMPLATE, "format": "a3"}]
    assert post(owner, "/api/backup/restore", doc).status_code == 400
    assert owner.get("/api/preferences").get_json()["label_templates"] == kept
