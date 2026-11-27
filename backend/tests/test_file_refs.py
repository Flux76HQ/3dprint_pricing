"""Where the files of a 3D model are kept outside the app (a cloud drive, a NAS): a list of kind, name and location that is only remembered, never opened by the server, and
of which only a safe form is accepted, so that nothing the screen turns into a link can run anything."""
import pytest

from app import api, api_keys
from tests.test_auth_api import H, post
from tests.test_backup import backup
from tests.test_domain_api import make, sheet_payload
from tests.test_integrations import bearer, new_key
from tests.test_users import _reset_limits, owner      # noqa: F401  (fixtures: the owner has a passkey, which an API key is made with)


@pytest.fixture(autouse=True)
def _fresh_limiters():
    api_keys.per_key.hits.clear()
    api_keys.wrong_key.hits.clear()

PLACES = [
    ("gdrive", "https://drive.google.com/drive/folders/1AbC?usp=sharing"),
    ("onedrive", "https://1drv.ms/f/s!AbCdEf"),
    ("icloud", "https://www.icloud.com/iclouddrive/0abc#Vaas"),
    ("dropbox", "https://www.dropbox.com/scl/fo/abc/def?rlkey=1"),
    ("nas", "smb://nas.local/prints/Mijn vazen/2026"),                   # a path may hold spaces
    ("nas", r"\\nas\prints\Mijn vazen"),
    ("nas", r"Z:\Prints\Vaas"),
    ("nas", "file:///Volumes/prints/Vaas"),
    ("other", "http://intern.example.test/bestanden"),
]


def with_refs(refs, **extra):
    return {**sheet_payload(), "file_refs": refs, **extra}


def ref(location, kind="other", label=""):
    return {"kind": kind, "label": label, "location": location}


@pytest.mark.parametrize("kind, location", PLACES)
def test_every_place_a_person_would_paste_is_kept_as_it_was_typed(owner, kind, location):
    saved = make(owner, "/api/projects", with_refs([ref(location, kind, "Slicer-projecten")]))
    assert saved["file_refs"] == [{"kind": kind, "label": "Slicer-projecten", "location": location}]
    assert owner.get(f"/api/projects/{saved['id']}").get_json()["file_refs"] == saved["file_refs"]


@pytest.mark.parametrize("location", [
    "javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://nas/prints", "vbscript:x", "nas/prints/vaas", "/mnt/nas/vaas", "\\\\", "\\\\ nas", "https://", "smb://",
    "https://a.test/x y", "https://a.test/x\nhttps://b.test", "Z:prints", "  ", ""])
def test_a_place_that_could_run_something_or_is_no_place_is_refused(owner, location):
    res = owner.post("/api/projects", json=with_refs([ref(location)]), headers=H)
    error = res.get_json()["error"]
    assert res.status_code == 400 and ("bestandslocatie" in error or ("verplicht" in error and not location.strip())), (location, error)       # empty: "required", anything else: what is allowed


def test_the_list_needs_to_be_a_list_of_places_of_a_known_kind_and_not_too_long(owner):
    for bad in ("x", {"location": "https://a.test"}, ["https://a.test"], [{"location": "https://a.test", "kind": "geheim"}],
                [ref("https://a.test/%d" % n) for n in range(api.MAX_FILE_REFS + 1)], [ref("https://a.test/" + "x" * 500)], [ref("https://a.test", label="n" * 61)]):
        assert owner.post("/api/projects", json=with_refs(bad), headers=H).status_code == 400, bad
    ok = owner.post("/api/projects", json=with_refs([ref("https://a.test/%d" % n) for n in range(api.MAX_FILE_REFS)]), headers=H)
    assert ok.status_code == 201 and len(ok.get_json()["file_refs"]) == api.MAX_FILE_REFS
    assert make(owner, "/api/projects", with_refs([{"location": "smb://nas/a"}]))["file_refs"][0]["kind"] == "other"          # no kind: other


def test_a_model_without_places_has_an_empty_list_and_an_update_without_them_leaves_them_alone(owner):
    plain = make(owner, "/api/projects", sheet_payload())
    assert plain["file_refs"] == []
    saved = make(owner, "/api/projects", with_refs([ref("smb://nas/prints/vaas", "nas")]))
    # a client that does not know the field (an app left open during an update) must not wipe what was typed
    changed = owner.put(f"/api/projects/{saved['id']}", json={**sheet_payload(), "name": "Anders"}, headers=H)
    assert changed.status_code == 200 and changed.get_json()["name"] == "Anders" and changed.get_json()["file_refs"] == saved["file_refs"]
    # one that sends the list replaces it, and an empty list takes them all away
    new = [ref("https://drive.google.com/x", "gdrive")]
    assert owner.put(f"/api/projects/{saved['id']}", json=with_refs(new), headers=H).get_json()["file_refs"] == new
    assert owner.put(f"/api/projects/{saved['id']}", json=with_refs([]), headers=H).get_json()["file_refs"] == []


def test_the_places_come_back_with_a_backup_and_an_older_backup_without_them_still_restores(owner):
    saved = make(owner, "/api/projects", with_refs([ref("smb://nas/prints/vaas", "nas", "NAS"), ref("https://1drv.ms/f/s!A", "onedrive")]))
    doc = backup(owner).get_json()
    assert doc["projects"][0]["file_refs"] == saved["file_refs"]
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert owner.get(f"/api/projects/{saved['id']}").get_json()["file_refs"] == saved["file_refs"]
    for project in doc["projects"]:
        project.pop("file_refs")                                                                   # a backup from before this existed
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert owner.get(f"/api/projects/{saved['id']}").get_json()["file_refs"] == []
    doc["projects"][0]["file_refs"] = [ref("javascript:alert(1)")]                                   # one that holds something unsafe is refused
    assert post(owner, "/api/backup/restore", doc).status_code == 400


def test_a_copy_of_a_model_keeps_the_places_and_other_applications_never_see_them(owner, app):
    key = new_key(owner)["key"]
    saved = make(owner, "/api/projects", with_refs([ref(r"\\nas\prints\vaas", "nas")]))
    copy = make(owner, "/api/projects", {**with_refs(saved["file_refs"]), "name": "Vaas (kopie)", "duplicate_of": saved["id"]})
    assert copy["file_refs"] == saved["file_refs"]
    # the paths of a private network are the owner's: not in the list of models, and not in what the read-only API gives for an item for sale
    assert all("file_refs" not in p for p in owner.get("/api/projects").get_json())
    assert owner.put(f"/api/projects/{saved['id']}/listing", json={"title": "Vaas", "description": "x", "price": "9.00"}, headers=H).status_code == 200
    seen = app.test_client().get("/api/v1/items", headers=bearer(key))
    assert seen.status_code == 200 and seen.get_json()["data"]
    for word in ("nas", "prints", "file_refs", "location"):
        assert word not in seen.get_data(as_text=True), word


# --- the screens ----------------------------------------------------------------------------------------------------------

def test_the_screen_and_the_server_know_the_same_kinds_of_place_and_the_cards_are_where_they_should_be():
    """No browser here, so the wiring is checked in the sources (the behaviour was checked in Chromium, on a desktop and a phone): the kinds the screen offers are the kinds the server
    accepts, the file locations and the links are cards of their own under the project (the locations first) and above the print file, which is only called that, and the button
    that makes the pictures is in the block of the photos, not between the blocks."""
    import json
    import re
    from pathlib import Path
    front = Path(__file__).resolve().parents[2] / "frontend"
    projects = (front / "js/projects.js").read_text()
    kinds = re.search(r"PLACE_KINDS = \[(.*?)\];", projects, re.S).group(1)
    assert tuple(re.findall(r"\['(\w+)', 'place\.\w+'\]", kinds)) == api.FILE_KINDS
    nl = json.loads((front / "lang/nl.json").read_text())
    assert all(f"place.{kind}" in nl for kind in api.FILE_KINDS) and nl["file.title"] == "Printbestand"
    assert "placesBox,\n        linksBox,\n        fileBox," in projects                              # under the project card, above the print file
    assert "fill(fileBox, ...parts, modelsBox());" in projects and "linksBox" not in projects[projects.index("function drawFile()"):projects.index("// what the linked models are called")]
    assert "file_refs: state.file_refs.filter((r) => r.location.trim())" in projects
    card = (front / "js/ai-images.js").read_text()
    assert card.index("onclick: generate") < card.index("], { count: sourceCount })")                 # in the block of the photos and views
    assert card.count("onclick: generate") == 1 and "|| working, onclick: generate" in card         # and it waits while pictures are being made


def test_the_cards_of_file_locations_and_links_fold_and_show_an_icon_for_each_that_was_made_while_folded():
    """The two cards fold away on their own (`foldHead`, remembered in the browser); folded, the heading shows one icon for each location or link that has an address, made again
    whenever one changes (so it never lags behind what was typed), and every kind the server knows has an icon of its own to be shown with (checked in Chromium on a desktop and a phone)."""
    import re
    from pathlib import Path
    front = Path(__file__).resolve().parents[2] / "frontend"
    projects = (front / "js/projects.js").read_text()
    assert "foldHead('model-places', t('place.title'), { extra: placeIcons })" in projects and "foldHead('model-links', t('file.links_title'), { extra: linkIcons })" in projects
    assert "state.file_refs.filter((r) => r.location.trim())" in projects.split("const drawPlaceIcons")[1].split("function drawPlaces")[0]        # an empty line is not an icon yet
    assert "state.links.filter((l) => l.url.trim())" in projects.split("const drawLinkIcons")[1].split("function drawLinks")[0]
    assert len(re.findall(r"\bdrawPlaceIcons\b", projects)) >= 5 and len(re.findall(r"\bdrawLinkIcons\b", projects)) >= 5      # defined, and used when the kind, the address or the name changes and when the card is drawn
    links = (front / "js/links.js").read_text()
    for source, table, kinds in ((projects, "PLACE_ICONS", api.FILE_KINDS), (links, "LINK_ICONS", api.LINK_KINDS)):
        listed = re.search(rf"const {table} = \{{(.*?)\}};", source, re.S).group(1)
        assert tuple(re.findall(r"(\w+): '[\w-]+'", listed)) == kinds, table                          # a kind the server accepts but the screen has no icon for would show nothing
    ui = (front / "js/ui.js").read_text()
    drawn = ui + (front / "js/mdi.js").read_text() + (front / "js/brands.js").read_text()               # where `icon()` finds an icon: its own, Material Design, or the mark of a shop
    used = set(re.findall(r": '([\w-]+)'", re.search(r"const PLACE_ICONS = \{(.*?)\};", projects, re.S).group(1) + re.search(r"const LINK_ICONS = \{(.*?)\};", links, re.S).group(1)))
    assert all(f"  {name}: '" in drawn or f"'{name}': '" in drawn for name in used), used
    css = (front / "css/app.css").read_text()
    assert '.fold-toggle[aria-expanded="true"] .fold-icons { display: none; }' in css.replace("\n", " ") or ".fold-icons:empty, .fold-toggle[aria-expanded=\"true\"] .fold-icons { display: none; }" in css
