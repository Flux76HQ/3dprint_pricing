"""A packaging item can have a picture: a photo of the box or bag, or its logo.

It is an untrusted upload like the others: decoded, scaled down and written again, kept in the database, gone with its item, and in the backup."""
import io

import pytest
from PIL import Image

from tests.test_auth_api import H, onboard, post
from tests.test_backup import backup, wipe
from tests.test_domain_api import make


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def picture(size=(1600, 1200), mode="RGB", colour=(200, 120, 40), kind="JPEG", **save):
    out = io.BytesIO()
    Image.new(mode, size, colour).save(out, kind, **save)
    return out.getvalue()


def put(client, item_id, content, name="doos.jpg"):
    return client.put(f"/api/packaging-images/{item_id}", data={"file": (io.BytesIO(content), name)}, content_type="multipart/form-data", headers=H)


def box(owner, name="Verzenddoos S"):
    return make(owner, "/api/packaging", {"name": name, "price": "0.42"})


def test_the_picture_is_scaled_down_and_written_again_as_a_jpeg(owner):
    item = box(owner)
    assert owner.get("/api/packaging-images").get_json() == {"images": {}}
    exif = Image.Exif()
    exif[0x010F] = "Phone maker"                                     # what a phone writes into a photo; none of it may be kept
    res = put(owner, item["id"], picture(exif=exif))
    assert res.status_code == 200 and (res.get_json()["width_px"], res.get_json()["height_px"]) == (800, 600)
    version = owner.get("/api/packaging-images").get_json()["images"][item["id"]]
    assert version == res.get_json()["version"]
    served = owner.get(f"/api/packaging-images/{item['id']}")
    assert served.mimetype == "image/jpeg" and b"Phone maker" not in served.data
    with Image.open(io.BytesIO(served.data)) as image:
        assert image.format == "JPEG" and image.size == (800, 600) and not image.getexif()


def test_a_png_with_transparency_becomes_a_picture_on_white(owner):
    item = box(owner)
    assert put(owner, item["id"], picture((300, 200), "RGBA", (0, 0, 0, 0), "PNG"), "logo.png").status_code == 200
    with Image.open(io.BytesIO(owner.get(f"/api/packaging-images/{item['id']}").data)) as image:
        assert image.format == "JPEG" and image.size == (300, 200) and image.getpixel((5, 5))[0] > 240


def test_a_new_picture_replaces_the_old_one_and_changes_its_version(owner):
    item = box(owner)
    first = put(owner, item["id"], picture(colour=(10, 10, 10))).get_json()["version"]
    second = put(owner, item["id"], picture(colour=(250, 250, 250))).get_json()["version"]
    assert first != second and owner.get("/api/packaging-images").get_json()["images"] == {item["id"]: second}


def test_the_browser_keeps_a_picture_under_the_address_of_its_version_only(owner):
    """The list asks for `?v=<version>`, and the version is the hash of the picture: only that address can never change what it gives.
    Before, every picture was fetched again at every visit of the list (docs/performance.md)."""
    item = box(owner)
    first = put(owner, item["id"], picture(colour=(10, 20, 30))).get_json()["version"]
    kept = owner.get(f"/api/packaging-images/{item['id']}?v={first}")
    assert kept.status_code == 200 and kept.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert owner.get(f"/api/packaging-images/{item['id']}?v={first}", headers={"If-None-Match": kept.headers["ETag"]}).status_code == 304
    for address in (f"/api/packaging-images/{item['id']}", f"/api/packaging-images/{item['id']}?v=", f"/api/packaging-images/{item['id']}?v=0123456789abcdef"):
        assert owner.get(address).headers["Cache-Control"] == "no-store", address
    second = put(owner, item["id"], picture(colour=(200, 20, 30))).get_json()["version"]
    assert second != first
    old = owner.get(f"/api/packaging-images/{item['id']}?v={first}")                    # the address of the picture that was replaced
    assert old.headers["Cache-Control"] == "no-store" and old.data != kept.data          # gives the new one, and that is not kept under the old address
    new = owner.get(f"/api/packaging-images/{item['id']}?v={second}")
    assert new.headers["Cache-Control"] == "private, max-age=31536000, immutable" and new.data == old.data
    assert owner.get("/api/packaging-images").headers["Cache-Control"] == "no-store"     # which pictures there are is asked every time


def test_it_can_be_removed_and_goes_with_its_item(owner):
    one, two = box(owner), box(owner, "Luchtkussenenvelop")
    put(owner, one["id"], picture())
    put(owner, two["id"], picture())
    assert owner.delete(f"/api/packaging-images/{one['id']}", headers=H).status_code == 200
    assert owner.get(f"/api/packaging-images/{one['id']}").status_code == 404
    assert owner.delete(f"/api/packaging/{two['id']}", headers=H).status_code in (200, 204)
    assert owner.get("/api/packaging-images").get_json() == {"images": {}}


@pytest.mark.parametrize("content, name", [(b"not a picture at all", "doos.jpg"), (b"%PDF-1.7 ...", "doos.png"), (b"", "leeg.jpg")])
def test_what_is_not_a_picture_is_refused(owner, content, name):
    item = box(owner)
    assert put(owner, item["id"], content, name).status_code == 400
    assert owner.get("/api/packaging-images").get_json() == {"images": {}}


def test_a_request_without_a_file_or_for_an_unknown_item_is_refused(owner):
    item = box(owner)
    assert owner.put(f"/api/packaging-images/{item['id']}", data={}, content_type="multipart/form-data", headers=H).status_code == 400
    assert put(owner, "00000000-0000-4000-8000-000000000000", picture()).status_code == 404
    assert owner.get("/api/packaging-images/00000000-0000-4000-8000-000000000000").status_code == 404


def test_the_pictures_need_a_session(client, owner):
    item = box(owner)
    put(owner, item["id"], picture())
    client.delete_cookie("pp_session")
    assert client.get("/api/packaging-images").status_code == 401
    assert client.get(f"/api/packaging-images/{item['id']}").status_code == 401
    assert put(client, item["id"], picture()).status_code == 401


def test_the_pictures_come_back_with_a_backup(owner):
    item = box(owner)
    put(owner, item["id"], picture((640, 480)))
    before = owner.get(f"/api/packaging-images/{item['id']}").data
    doc = backup(owner).get_json()
    assert [entry["packaging_id"] for entry in doc["packaging_images"]] == [item["id"]]
    wipe(owner)
    assert owner.get("/api/packaging-images").get_json() == {"images": {}}
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert list(owner.get("/api/packaging-images").get_json()["images"]) == [item["id"]]
    with Image.open(io.BytesIO(owner.get(f"/api/packaging-images/{item['id']}").data)) as restored, Image.open(io.BytesIO(before)) as original:
        assert restored.size == original.size == (640, 480)


def test_a_backup_from_before_the_pictures_restores_and_a_bad_picture_stops_the_restore(owner):
    item = box(owner)
    put(owner, item["id"], picture())
    doc = backup(owner).get_json()
    older = {key: value for key, value in doc.items() if key != "packaging_images"}
    assert post(owner, "/api/backup/restore", older).status_code == 200
    assert owner.get("/api/packaging-images").get_json() == {"images": {}}
    for broken in ({"packaging_id": item["id"], "content_b64": "!!geen base64!!"},
                   {"packaging_id": "00000000-0000-4000-8000-000000000000", "content_b64": doc["packaging_images"][0]["content_b64"]},
                   {"packaging_id": item["id"], "content_b64": "bm90IGEgcGljdHVyZQ=="}):
        res = post(owner, "/api/backup/restore", {**doc, "packaging_images": [broken]}, headers={**H, "X-Lang": "nl"})
        assert res.status_code == 400 and "Afbeeldingen van verpakking" in res.get_json()["error"], res.get_json()
