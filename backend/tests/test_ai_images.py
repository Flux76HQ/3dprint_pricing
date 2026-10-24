"""AI product images: off unless AI_IMAGES_ENABLED, the OpenAI key is encrypted and never shown again, photos are re-encoded, the
request to OpenAI is what we say it is, and the pictures survive a backup (the key does not)."""
import base64
import dataclasses
from io import BytesIO

import psycopg
import pytest
import requests
from PIL import Image

from app import ai_images
from tests.test_auth_api import H, onboard, post
from tests.test_backup import backup
from tests.test_domain_api import make, sheet_payload

KEY = "sk-test-0123456789abcdefghijklmnop"


@pytest.fixture
def owner(client):
    onboard(client)
    return client


@pytest.fixture
def ai(app, owner):
    """The same app with the feature switched on, as AI_IMAGES_ENABLED=TRUE does."""
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], ai_images_enabled=True)
    return owner


def png(size=(300, 200), colour=(200, 40, 40), mode="RGB"):
    out = BytesIO()
    Image.new(mode, size, colour).save(out, "PNG")
    return out.getvalue()


def photo(owner, project, data=None, name="foto.png"):
    return owner.post(f"/api/projects/{project}/images/source", data={"file": (BytesIO(png() if data is None else data), name)}, headers=H,
                      content_type="multipart/form-data")


class FakeOpenAI:
    """Stands in for requests.request: records the call and answers like the images API."""

    def __init__(self, monkeypatch, *, status=200, error=None, raises=None, result=None):
        self.calls, self.status, self.error, self.raises = [], status, error, raises
        self.result = result if result is not None else png((64, 64), (10, 120, 10))
        monkeypatch.setattr(ai_images.requests, "request", self)

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.raises:
            raise self.raises
        res = requests.Response()
        res.status_code = self.status
        if self.status >= 400:
            res._content = ('{"error": %s}' % (self.error or "{}")).encode()
        else:
            res._content = ('{"data": [{"b64_json": "%s"}]}' % base64.b64encode(self.result).decode()).encode()
        return res


@pytest.fixture
def project(ai):
    return make(ai, "/api/projects", {**sheet_payload(), "object_description": "plantenbak voor op een vensterbank"})


def set_key(owner):
    res = owner.put("/api/ai-images/settings", json={"api_key": KEY}, headers=H)
    assert res.status_code == 200, res.get_json()
    return res


# --- the switch -----------------------------------------------------------------------------------------------------

def test_the_feature_does_not_exist_without_the_flag(owner, app):
    assert owner.get("/api/auth/status").get_json()["ai_images"] is False
    pid = make(owner, "/api/projects", sheet_payload())["id"]
    assert owner.get("/api/ai-images/settings").status_code == 404
    assert owner.put("/api/ai-images/settings", json={"api_key": KEY}, headers=H).status_code == 404
    assert owner.get(f"/api/projects/{pid}/images").status_code == 404
    assert photo(owner, pid).status_code == 404
    assert post(owner, f"/api/projects/{pid}/images/generate", {"variant": "square"}).status_code == 404


def test_the_flag_is_read_from_the_environment(monkeypatch):
    from app.config import _flag
    for value, expected in (("TRUE", True), ("true", True), (" True ", True), ("1", True), ("FALSE", False), ("", False), ("nope", False)):
        monkeypatch.setenv("AI_IMAGES_ENABLED", value)
        assert _flag("AI_IMAGES_ENABLED") is expected, value
    monkeypatch.delenv("AI_IMAGES_ENABLED")
    assert _flag("AI_IMAGES_ENABLED") is False


def test_the_flag_is_reported_to_the_app(ai):
    assert ai.get("/api/auth/status").get_json()["ai_images"] is True


def test_a_session_is_needed_even_with_the_flag(app, client):
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], ai_images_enabled=True)
    assert client.get("/api/ai-images/settings").status_code == 401


# --- the key ----------------------------------------------------------------------------------------------------------

def test_the_key_is_encrypted_and_never_shown(ai, app):
    assert ai.get("/api/ai-images/settings").get_json() == {"configured": False, "readable": True, "last4": "", "model": "gpt-image-2",
                                                            "quality": "medium"}
    res = set_key(ai)
    assert res.get_json()["last4"] == KEY[-4:] and res.get_json()["configured"] is True
    assert KEY not in res.get_data(as_text=True) and KEY not in ai.get("/api/ai-images/settings").get_data(as_text=True)
    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        stored = conn.execute("SELECT api_key_enc FROM ai_image_settings").fetchone()[0]
    assert KEY not in stored and stored.startswith("gAAAA")
    # changing the model keeps the key
    res = ai.put("/api/ai-images/settings", json={"model": "gpt-image-2-mini", "quality": "high"}, headers=H).get_json()
    assert res["last4"] == KEY[-4:] and res["model"] == "gpt-image-2-mini" and res["quality"] == "high"
    res = ai.delete("/api/ai-images/key", headers=H).get_json()
    assert res["configured"] is False and res["model"] == "gpt-image-2-mini"


def test_a_key_that_cannot_be_decrypted_fails_closed(ai, app, monkeypatch):
    set_key(ai)
    with psycopg.connect(app.config["APP_CONFIG"].database_url, autocommit=True) as conn:         # what a rotated SESSION_SECRET leaves behind
        conn.execute("UPDATE ai_image_settings SET api_key_enc = %s", (ai_images.passwords.seal("y" * 40, KEY.encode(), ai_images.KEY_INFO).decode(),))
    assert ai.get("/api/ai-images/settings").get_json()["readable"] is False
    fake = FakeOpenAI(monkeypatch)
    res = post(ai, "/api/ai-images/test")
    assert res.status_code == 400 and not fake.calls


@pytest.mark.parametrize("body", [{"api_key": "short"}, {"api_key": "has a space in it 0123456789"}, {"model": "../etc"},
                                  {"model": ""}, {"quality": "ultra"}])
def test_settings_are_validated(ai, body):
    assert ai.put("/api/ai-images/settings", json=body, headers=H).status_code == 400


def test_the_connection_test_asks_for_the_model(ai, monkeypatch):
    set_key(ai)
    fake = FakeOpenAI(monkeypatch)
    assert post(ai, "/api/ai-images/test").get_json() == {"ok": True}
    call = fake.calls[0]
    assert call["method"] == "GET" and call["url"] == "https://api.openai.com/v1/models/gpt-image-2"
    assert call["headers"] == {"Authorization": f"Bearer {KEY}"}


def test_the_connection_test_without_a_key(ai, monkeypatch):
    fake = FakeOpenAI(monkeypatch)
    assert post(ai, "/api/ai-images/test").status_code == 400 and not fake.calls


# --- the photo ----------------------------------------------------------------------------------------------------------

def test_a_photo_is_re_encoded_and_scaled(ai, project):
    exif = BytesIO()
    image = Image.new("RGB", (3000, 1000), (1, 2, 3))
    image.getexif()[0x010F] = "SecretCamera"                                  # Make
    image.save(exif, "JPEG", exif=image.getexif())
    assert b"SecretCamera" in exif.getvalue()
    res = photo(ai, project["id"], exif.getvalue(), "x.jpg")
    assert res.status_code == 201 and res.get_json()["width_px"] == 2048 and res.get_json()["kind"] == "source"
    stored = ai.get(f"/api/project-images/{res.get_json()['id']}/file")
    assert stored.mimetype == "image/jpeg" and b"SecretCamera" not in stored.data
    assert Image.open(BytesIO(stored.data)).size == (2048, 683)


def test_a_new_photo_replaces_the_old_one(ai, project):
    photo(ai, project["id"])
    second = photo(ai, project["id"], png((50, 50)))
    rows = ai.get(f"/api/projects/{project['id']}/images").get_json()
    assert [r["id"] for r in rows] == [second.get_json()["id"]]


@pytest.mark.parametrize("data", [b"not an image", b"GIF89a" + b"\x00" * 40, b""])
def test_something_that_is_not_a_photo_is_refused(ai, project, data):
    assert photo(ai, project["id"], data).status_code == 400


def test_a_photo_for_a_missing_calculation(ai):
    assert photo(ai, "00000000-0000-0000-0000-000000000000").status_code == 404


# --- generating ---------------------------------------------------------------------------------------------------------

def test_the_request_to_openai(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    fake = FakeOpenAI(monkeypatch)
    res = post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "landscape"})
    assert res.status_code == 201 and res.get_json()["variant"] == "landscape" and res.get_json()["kind"] == "generated"
    call = fake.calls[0]
    assert (call["method"], call["url"]) == ("POST", "https://api.openai.com/v1/images/edits")
    assert call["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert call["data"]["model"] == "gpt-image-2" and call["data"]["size"] == "1536x1024" and call["data"]["quality"] == "medium"
    assert "plantenbak voor op een vensterbank" in call["data"]["prompt"]
    name, content, mime = call["files"]["image"]
    assert mime == "image/jpeg" and Image.open(BytesIO(content)).size == (300, 200)
    shown = ai.get(f"/api/project-images/{res.get_json()['id']}/file")
    assert Image.open(BytesIO(shown.data)).size == (64, 64)


def test_a_description_from_the_form_wins_over_the_saved_one(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    fake = FakeOpenAI(monkeypatch)
    post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square", "description": "sleutelhanger"})
    assert "sleutelhanger" in fake.calls[0]["data"]["prompt"] and "plantenbak" not in fake.calls[0]["data"]["prompt"]
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square", "description": "x" * 501}).status_code == 400


def test_the_prompt():
    for variant in ai_images.VARIANTS:
        prompt = ai_images.build_prompt(variant, "plantenbak")
        assert "real photograph" in prompt and "no 3D render" in prompt
    assert "plantenbak" in ai_images.build_prompt("square", "  plantenbak\n voor ")
    assert "plantenbak" not in ai_images.build_prompt("studio", "plantenbak")      # a studio picture has no setting
    assert "The object is:" not in ai_images.build_prompt("square", "")
    assert "x" * 500 in ai_images.build_prompt("square", "x" * 5000) and "x" * 501 not in ai_images.build_prompt("square", "x" * 5000)


def test_nothing_is_sent_without_a_key_or_a_photo(ai, project, monkeypatch):
    fake = FakeOpenAI(monkeypatch)
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square"}).status_code == 400    # no key
    set_key(ai)
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square"}).status_code == 400    # no photo
    photo(ai, project["id"])
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "wide"}).status_code == 400      # unknown variant
    assert not fake.calls


@pytest.mark.parametrize("status,error,expected", [
    (401, '{"code": "invalid_api_key"}', 400),
    (429, '{"code": "insufficient_quota"}', 429),
    (429, '{"code": "rate_limit_exceeded"}', 429),
    (400, '{"code": "moderation_blocked", "message": "no"}', 422),
    (400, '{"message": "Invalid size"}', 400),
    (404, '{"message": "model not found"}', 400),
    (503, '{}', 502),
])
def test_what_openai_refuses_becomes_a_message(ai, project, monkeypatch, status, error, expected):
    set_key(ai)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch, status=status, error=error)
    res = post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square"})
    assert res.status_code == expected
    assert KEY not in res.get_data(as_text=True)
    assert ai.get(f"/api/projects/{project['id']}/images").get_json()[0]["kind"] == "source"       # nothing was stored


def test_the_message_names_the_reason(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch, status=400, error='{"message": "Invalid size 9x9"}')
    res = ai.post(f"/api/projects/{project['id']}/images/generate", json={"variant": "square"}, headers={**H, "X-Lang": "en"})
    assert "Invalid size 9x9" in res.get_json()["error"]


def test_timeouts_and_connection_errors(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch, raises=requests.Timeout())
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square"}).status_code == 504
    FakeOpenAI(monkeypatch, raises=requests.ConnectionError())
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square"}).status_code == 502


def test_an_answer_that_is_no_image_is_refused(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch, result=b"this is not an image")
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square"}).status_code == 502


def test_the_number_of_pictures_is_capped(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch)
    for _ in range(ai_images.MAX_GENERATED):
        assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "studio"}).status_code == 201
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "studio"}).status_code == 409


def test_generating_is_rate_limited(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch)
    monkeypatch.setattr(ai_images, "_limit", ai_images.RateLimiter(1, 3600))
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "studio"}).status_code == 201
    assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "studio"}).status_code == 429


# --- using the pictures -----------------------------------------------------------------------------------------------

def test_cover_download_and_delete(ai, project, monkeypatch):
    set_key(ai)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch)
    first = post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "square"}).get_json()
    second = post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "studio"}).get_json()
    listed = lambda: {p["id"]: p["cover_image_id"] for p in ai.get("/api/projects").get_json()}
    assert listed() == {project["id"]: None}
    assert ai.put(f"/api/project-images/{first['id']}/cover", headers=H).status_code == 200
    assert listed() == {project["id"]: first["id"]}
    ai.put(f"/api/project-images/{second['id']}/cover", headers=H)
    assert listed() == {project["id"]: second["id"]}                                 # one cover at a time
    download = ai.get(f"/api/project-images/{first['id']}/file?download=1")
    assert f"berekening-{project['number']}-square.jpg" in download.headers["Content-Disposition"]
    assert ai.delete(f"/api/project-images/{second['id']}", headers=H).status_code == 200
    assert listed() == {project["id"]: None} and ai.get(f"/api/project-images/{second['id']}/file").status_code == 404


def test_deleting_the_calculation_deletes_its_pictures(ai, project, app):
    photo(ai, project["id"])
    assert ai.delete(f"/api/projects/{project['id']}", headers=H).status_code == 200
    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        assert conn.execute("SELECT count(*) FROM project_images").fetchone()[0] == 0


def test_the_description_is_a_plain_project_field(owner):
    made = make(owner, "/api/projects", {**sheet_payload(), "object_description": "  vogelhuisje  "})
    assert made["object_description"] == "vogelhuisje"
    assert owner.get(f"/api/projects/{made['id']}").get_json()["object_description"] == "vogelhuisje"
    res = owner.put(f"/api/projects/{made['id']}", json={**sheet_payload(), "object_description": "x" * 501}, headers=H)
    assert res.status_code == 400
    assert owner.post("/api/projects", json=sheet_payload(), headers=H).get_json()["object_description"] == ""


# --- backup -------------------------------------------------------------------------------------------------------------

def test_pictures_and_the_description_survive_a_backup_but_the_key_does_not(ai, project, monkeypatch):
    set_key(ai)
    ai.put("/api/ai-images/settings", json={"model": "gpt-image-2-mini", "quality": "low"}, headers=H)
    photo(ai, project["id"])
    FakeOpenAI(monkeypatch)
    made = post(ai, f"/api/projects/{project['id']}/images/generate", {"variant": "portrait"}).get_json()
    ai.put(f"/api/project-images/{made['id']}/cover", headers=H)
    text = backup(ai).get_data(as_text=True)
    assert KEY not in text and "api_key" not in text
    doc = backup(ai).get_json()
    assert doc["projects"][0]["object_description"] == "plantenbak voor op een vensterbank"
    assert [i["kind"] for i in doc["project_images"]] == ["source", "generated"]

    ai.delete(f"/api/projects/{project['id']}", headers=H)
    assert post(ai, "/api/backup/restore", doc).status_code == 200
    restored = ai.get(f"/api/projects/{project['id']}").get_json()
    assert restored["object_description"] == "plantenbak voor op een vensterbank"
    images = ai.get(f"/api/projects/{project['id']}/images").get_json()
    assert [(i["kind"], i["variant"], i["is_cover"]) for i in images] == [("source", None, False), ("generated", "portrait", True)]
    assert ai.get("/api/projects").get_json()[0]["cover_image_id"] == images[1]["id"]
    assert ai.get("/api/ai-images/settings").get_json()["model"] == "gpt-image-2-mini"
    assert ai.get("/api/ai-images/settings").get_json()["last4"] == KEY[-4:]                    # the key was not touched by the restore


def test_a_backup_with_a_damaged_picture_is_refused_before_anything_changes(ai, project):
    photo(ai, project["id"])
    doc = backup(ai).get_json()
    doc["project_images"][0]["content_b64"] = base64.b64encode(b"not an image").decode()
    assert post(ai, "/api/backup/restore", doc).status_code == 400
    assert len(ai.get(f"/api/projects/{project['id']}/images").get_json()) == 1
    doc = backup(ai).get_json()
    doc["project_images"][0]["project_id"] = "00000000-0000-0000-0000-000000000000"
    assert post(ai, "/api/backup/restore", doc).status_code == 400


def test_an_older_backup_restores_with_an_empty_description(ai, project):
    doc = backup(ai).get_json()
    doc["format_version"] = 2
    for key in ("project_images", "ai_image_settings"):
        doc.pop(key, None)
    for row in doc["projects"]:
        row.pop("object_description")
    assert post(ai, "/api/backup/restore", doc).status_code == 200
    assert ai.get(f"/api/projects/{project['id']}").get_json()["object_description"] == ""
