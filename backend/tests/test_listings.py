"""A 3D model that is for sale has a listing: the title and text of the advertisement, a price that is typed (never derived), an EAN, and
photos in an order. It is the business's own data (in the backup), and another application reads it as an item, without what it costs."""
import io
import json
import uuid
import zipfile

import pytest
from PIL import Image

from app import api_keys, listings
from tests.test_auth_api import H, post
from tests.test_backup import backup, wipe
from tests.test_domain_api import make, sheet_payload
from tests.test_integrations import bearer, new_key
from tests.test_users import _reset_limits, join_with_passkey, owner, sql      # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _fresh_limiters():
    api_keys.per_key.hits.clear()
    api_keys.wrong_key.hits.clear()


def gtin(body: str) -> str:
    """`body` with its GS1 check digit behind it."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return body + str((10 - total % 10) % 10)


def picture(size=(1200, 900), colour=(200, 120, 40), kind="JPEG", **save):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, kind, **save)
    return out.getvalue()


def model(owner, name="Vaas Gyroïde", **extra):
    return make(owner, "/api/projects", {**sheet_payload(), "name": name, "margin_pct": "100", "vat_pct": "21", **extra})


def put(client, project, **fields):
    return client.put(f"/api/projects/{project['id']}/listing", json={"title": "Vaas, 3D-geprint", "description": "Waterdicht.\nIn zes kleuren.", "price": "14.95", **fields}, headers=H)


def upload(client, project, content=None, name="foto.jpg"):
    return client.post(f"/api/projects/{project['id']}/listing/photos", data={"file": (io.BytesIO(picture() if content is None else content), name)}, content_type="multipart/form-data", headers=H)


def product_picture(app, project, colour=(10, 90, 160)):
    """One of the model's product pictures, as the AI images leave them (written straight into the table: no OpenAI in a test)."""
    return sql(app, "INSERT INTO project_images (project_id, kind, variant, purpose, mime, content, width_px, height_px) VALUES (%s, 'generated', 'square', 'marktplaats', "
                    "'image/jpeg', %s, 1024, 1024) RETURNING id", (project["id"], picture((1024, 1024), colour)))[0]["id"]


def listed(client, project):
    return client.get(f"/api/projects/{project['id']}/listing").get_json()


# --- the listing -----------------------------------------------------------------------------------------------------------

def test_a_model_is_not_for_sale_until_it_has_a_listing(owner):
    vase = model(owner)
    assert listed(owner, vase) == {"listing": None, "photos": [], "max_photos": listings.MAX_PHOTOS}
    row = owner.get("/api/projects").get_json()[0]
    assert row["for_sale"] is False and row["listing_price"] is None
    saved = put(owner, vase)
    assert saved.status_code == 200 and saved.get_json()["listing"]["title"] == "Vaas, 3D-geprint" and saved.get_json()["listing"]["price"] == "14.95"
    row = owner.get("/api/projects").get_json()[0]
    assert row["for_sale"] is True and row["listing_price"] == "14.95"
    assert put(owner, vase, title="Vaas", price="").get_json()["listing"]["price"] is None           # saved again: the same listing, the price not decided
    assert sql(owner.application, "SELECT count(*) AS n FROM listings")[0]["n"] == 1


def test_the_price_is_typed_and_does_not_follow_the_calculation(owner):
    vase = model(owner)
    put(owner, vase, price="14.95")
    advised = owner.get(f"/api/projects/{vase['id']}").get_json()["totals"]["sell_price_incl_vat"]
    changed = owner.put(f"/api/projects/{vase['id']}", json={**sheet_payload(), "name": vase["name"], "margin_pct": "400", "vat_pct": "21"}, headers=H).get_json()
    assert changed["totals"]["sell_price_incl_vat"] != advised
    assert listed(owner, vase)["listing"]["price"] == "14.95"


def test_what_is_typed_is_checked(owner):
    vase = model(owner)
    good = gtin("871234567890")
    assert put(owner, vase, ean=good).get_json()["listing"]["ean"] == good
    assert put(owner, vase, ean=f" {good[:1]} {good[1:7]}-{good[7:]} ").get_json()["listing"]["ean"] == good        # typed with spaces and a dash
    for digits in (gtin("1234567"), gtin("12345678901"), gtin("1234567890123")):                          # 8, 12 and 14 digits
        assert put(owner, vase, ean=digits).status_code == 200, digits
    wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
    for bad in ({"ean": wrong}, {"ean": "87123ABC67890"}, {"ean": "12345"}, {"title": ""}, {"title": "x" * 81}, {"description": "x" * 4001},
                {"price": "-1"}, {"price": "veel"}, {"photos": "alle"}, {"photos": [str(uuid.uuid4())]}):
        assert put(owner, vase, **bad).status_code == 400, bad
    assert listed(owner, vase)["listing"]["ean"] == gtin("1234567890123")                                 # the last good one stands
    assert put(owner, {"id": str(uuid.uuid4())}).status_code == 404


def test_anyone_who_is_signed_in_keeps_the_listings_and_nobody_else(owner, app):
    vase = model(owner)
    member = join_with_passkey(app, owner)
    assert put(member, vase).status_code == 200 and upload(member, vase).status_code == 201
    stranger = app.test_client()
    photo = listed(owner, vase)["photos"][0]
    assert stranger.get(f"/api/projects/{vase['id']}/listing").status_code == 401
    assert stranger.get(photo["url"]).status_code == 401
    assert stranger.get(f"/api/projects/{vase['id']}/listing/photos.zip").status_code == 401
    assert put(stranger, vase).status_code == 401 and upload(stranger, vase).status_code == 401


# --- photos ------------------------------------------------------------------------------------------------------------------

def test_an_uploaded_photo_is_written_again_and_can_be_kept_by_the_browser(owner):
    vase = model(owner)
    exif = Image.Exif()
    exif[0x010F] = "Phone maker"
    added = upload(owner, vase, picture((4000, 3000), exif=exif))
    assert added.status_code == 201 and (added.get_json()["width_px"], added.get_json()["height_px"]) == (2048, 1536)
    served = owner.get(added.get_json()["url"])
    assert served.mimetype == "image/jpeg" and b"Phone maker" not in served.data and "immutable" in served.headers["Cache-Control"]
    again = owner.get(added.get_json()["url"], headers={"If-None-Match": served.headers["ETag"]})
    assert again.status_code == 304
    for content, name in ((b"not a picture", "foto.jpg"), (b"", "leeg.jpg")):
        assert upload(owner, vase, content, name).status_code == 400
    assert owner.post(f"/api/projects/{vase['id']}/listing/photos", json={}, headers=H).status_code == 400
    assert len(listed(owner, vase)["photos"]) == 1


def test_a_product_picture_is_taken_over_as_a_copy(owner, app):
    vase, other = model(owner), model(owner, "Sleutelhanger")
    image = product_picture(app, vase)
    foreign = product_picture(app, other)
    taken = owner.post(f"/api/projects/{vase['id']}/listing/photos", json={"image_id": str(image)}, headers=H)
    assert taken.status_code == 201 and taken.get_json()["width_px"] == 1024
    assert owner.post(f"/api/projects/{vase['id']}/listing/photos", json={"image_id": str(foreign)}, headers=H).status_code == 404      # another model's picture
    before = owner.get(taken.get_json()["url"]).data
    sql(app, "DELETE FROM project_images WHERE id = %s", (image,))                                    # the product picture is made again or removed
    assert owner.get(taken.get_json()["url"]).data == before


def test_the_photos_have_an_order_and_one_left_out_is_removed(owner, app, monkeypatch):
    vase, other = model(owner), model(owner, "Sleutelhanger")
    ids = [upload(owner, vase, picture(colour=(n * 60, 0, 0))).get_json()["id"] for n in range(3)]
    strange = upload(owner, other).get_json()["id"]
    assert [p["id"] for p in listed(owner, vase)["photos"]] == ids
    turned = put(owner, vase, photos=[ids[2], ids[0], ids[1]])
    assert [p["id"] for p in turned.get_json()["photos"]] == [ids[2], ids[0], ids[1]]
    assert put(owner, vase, photos=[ids[0], ids[0]]).status_code == 400                               # the same one twice
    assert put(owner, vase, photos=[ids[0], strange]).status_code == 400                              # a photo of another model
    assert [p["id"] for p in listed(owner, vase)["photos"]] == [ids[2], ids[0], ids[1]]               # a refused order changes nothing
    assert [p["id"] for p in put(owner, vase, photos=[ids[1], ids[2]]).get_json()["photos"]] == [ids[1], ids[2]]
    assert owner.get(f"/api/listing-photos/{ids[0]}/file").status_code == 404
    assert [p["id"] for p in put(owner, vase).get_json()["photos"]] == [ids[1], ids[2]]               # saving without naming them leaves them
    monkeypatch.setattr(listings, "MAX_PHOTOS", 2)
    assert upload(owner, vase).status_code == 409


def test_all_photos_come_in_one_file_numbered_in_their_order(owner):
    vase = model(owner)
    assert owner.get(f"/api/projects/{vase['id']}/listing/photos.zip").status_code == 404
    ids = [upload(owner, vase, picture((300 + n * 100, 300))).get_json()["id"] for n in range(3)]
    put(owner, vase, photos=[ids[1], ids[2], ids[0]])
    res = owner.get(f"/api/projects/{vase['id']}/listing/photos.zip")
    assert res.mimetype == "application/zip" and f"3d-model-{vase['number']}-fotos.zip" in res.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(res.data)) as archive:
        assert archive.namelist() == ["foto-01.jpg", "foto-02.jpg", "foto-03.jpg"]
        widths = [Image.open(io.BytesIO(archive.read(name))).width for name in archive.namelist()]
    assert widths == [400, 500, 300]


def test_taking_a_model_off_sale_keeps_the_model_and_removing_the_model_takes_everything(owner, app):
    vase, other = model(owner), model(owner, "Sleutelhanger")
    for item in (vase, other):
        put(owner, item)
        upload(owner, item)
    assert owner.delete(f"/api/projects/{vase['id']}/listing", headers=H).status_code == 200
    assert listed(owner, vase) == {"listing": None, "photos": [], "max_photos": listings.MAX_PHOTOS}
    assert owner.get(f"/api/projects/{vase['id']}").status_code == 200
    assert owner.delete(f"/api/projects/{other['id']}", headers=H).status_code in (200, 204)
    assert sql(app, "SELECT count(*) AS n FROM listings")[0]["n"] == 0 and sql(app, "SELECT count(*) AS n FROM listing_photos")[0]["n"] == 0


# --- in the backup ---------------------------------------------------------------------------------------------------------------

def test_listings_and_their_photos_come_back_with_a_backup(owner, app):
    vase = model(owner)
    ids = [upload(owner, vase, picture((300 + n * 100, 300))).get_json()["id"] for n in range(2)]
    put(owner, vase, ean=gtin("871234567890"), photos=[ids[1], ids[0]])
    doc = backup(owner).get_json()
    assert [(entry["title"], entry["price"], len(entry["photos"])) for entry in doc["listings"]] == [("Vaas, 3D-geprint", "14.95", 2)]
    wipe(owner)
    assert sql(app, "SELECT count(*) AS n FROM listings")[0]["n"] == 0
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    back = listed(owner, vase)
    assert (back["listing"]["title"], back["listing"]["description"], back["listing"]["price"], back["listing"]["ean"]) == \
        ("Vaas, 3D-geprint", "Waterdicht.\nIn zes kleuren.", "14.95", gtin("871234567890"))
    assert [p["width_px"] for p in back["photos"]] == [400, 300]                                       # the photos, in their order
    older = {key: value for key, value in doc.items() if key != "listings"}                            # a file from before the listings
    assert post(owner, "/api/backup/restore", older).status_code == 200 and listed(owner, vase)["listing"] is None
    entry = doc["listings"][0]
    for broken in ({**entry, "project_id": str(uuid.uuid4())}, {**entry, "photos": ["bm90IGEgcGljdHVyZQ=="]}, {**entry, "photos": ["!!"]},
                   {**entry, "ean": "123"}, {**entry, "title": ""}, {**entry, "photos": entry["photos"] * 7}):
        res = post(owner, "/api/backup/restore", {**doc, "listings": [broken]}, headers={**H, "X-Lang": "nl"})
        assert res.status_code == 400 and "Verkoopitems" in res.get_json()["error"], res.get_json()
    assert post(owner, "/api/backup/restore", {**doc, "listings": [entry, entry]}).status_code == 400   # one per model


# --- for another application: an item ------------------------------------------------------------------------------------------------

def test_another_application_reads_an_item_without_what_it_costs(owner, app):
    key = new_key(owner)["key"]
    vase = model(owner, links=[{"kind": "marktplaats", "label": "", "url": "https://www.marktplaats.nl/v/a1"}], notes="Alleen voor onszelf")
    hidden = model(owner, "Niet te koop")
    photo = upload(owner, vase).get_json()
    put(owner, vase, ean=gtin("871234567890"))
    reader = app.test_client()
    listed_items = reader.get("/api/v1/items", headers=bearer(key))
    assert listed_items.status_code == 200 and listed_items.get_json()["next_cursor"] is None
    text = listed_items.get_data(as_text=True)
    for word in ("cost_price", "margin", "totals", "Alleen voor onszelf", "Niet te koop", "filament"):
        assert word not in text, word
    item = listed_items.get_json()["data"][0]
    assert item == reader.get(f"/api/v1/items/{vase['id']}", headers=bearer(key)).get_json()
    assert (item["id"], item["number"], item["title"], item["price"], item["vat_pct"], item["ean"]) == \
        (vase["id"], vase["number"], "Vaas, 3D-geprint", "14.95", "21.00", gtin("871234567890"))
    assert item["links"] == [{"kind": "marktplaats", "label": "", "url": "https://www.marktplaats.nl/v/a1"}]
    assert item["photos"] == [{"id": photo["id"], "width": 1200, "height": 900, "url": f"/api/v1/items/{vase['id']}/photos/{photo['id']}"}]
    picture_res = reader.get(item["photos"][0]["url"], headers=bearer(key))
    assert picture_res.status_code == 200 and picture_res.mimetype == "image/jpeg"
    assert reader.get(f"/api/v1/items/{hidden['id']}", headers=bearer(key)).status_code == 404        # a model without a listing is not an item
    assert reader.get(f"/api/v1/items/{hidden['id']}/photos/{photo['id']}", headers=bearer(key)).status_code == 404
    waiting = upload(owner, hidden).get_json()                        # a photo put ready for a model that is not for sale yet
    assert owner.get(waiting["url"]).status_code == 200
    assert reader.get(f"/api/v1/items/{hidden['id']}/photos/{waiting['id']}", headers=bearer(key)).status_code == 404
    assert owner.get("/api/v1/items").status_code == 401 and reader.get(photo["url"], headers=bearer(key)).status_code == 401       # each door has its own key
    owner.delete(f"/api/projects/{vase['id']}/listing", headers=H)
    assert reader.get(item["photos"][0]["url"], headers=bearer(key)).status_code == 404
    assert reader.get("/api/v1/items", headers=bearer(key)).get_json()["data"] == []


def test_a_stored_photo_is_never_rewritten():
    """The browser keeps a photo for good under its id (`http.keep_forever`). That holds only while its bytes never change: every `UPDATE` of
    the table is listed here, and one that sets anything but the position needs a new id for the photo, or the caching has to go."""
    import re
    from pathlib import Path
    updates = []
    for path in sorted((Path(__file__).resolve().parent.parent / "app").glob("*.py")):
        updates += re.findall(r"UPDATE listing_photos SET (.+?) WHERE", path.read_text(encoding="utf-8"))
    assert updates == ["position = %s"]

