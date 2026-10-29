"""AI product images: off unless AI_IMAGES_ENABLED, the OpenAI key is encrypted and never shown again, photos are re-encoded, the
request to OpenAI is what we say it is, and the pictures survive a backup (the key does not)."""
import base64
import dataclasses
import json
from io import BytesIO

import pytest
import requests
from PIL import Image

from app import ai_images
from tests.test_auth_api import H, onboard, post
from tests.test_backup import backup
from tests.test_domain_api import make, sheet_payload
from tests.conftest import connect

KEY = "sk-test-0123456789abcdefghijklmnop"
REAL_START = ai_images._start


@pytest.fixture(autouse=True)
def _inline(monkeypatch):
    """The pictures are made in a thread; here they are made on the spot, so a test sees the outcome. One test uses the real thread."""
    monkeypatch.setattr(ai_images, "_start", lambda app, project_id, batch: ai_images._run_batch(app, project_id, batch))
    ai_images._limit.hits.clear()


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
    assert post(owner, f"/api/projects/{pid}/images/generate", {"variants": ["square"]}).status_code == 404
    assert owner.get("/api/ai-images/log").status_code == 404


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
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        stored = conn.execute("SELECT api_key_enc FROM ai_image_settings").fetchone()[0]
    assert KEY not in stored and stored.startswith("gAAAA")
    # changing the model keeps the key
    res = ai.put("/api/ai-images/settings", json={"model": "gpt-image-2-mini", "quality": "high"}, headers=H).get_json()
    assert res["last4"] == KEY[-4:] and res["model"] == "gpt-image-2-mini" and res["quality"] == "high"
    res = ai.delete("/api/ai-images/key", headers=H).get_json()
    assert res["configured"] is False and res["model"] == "gpt-image-2-mini"


def test_a_key_that_cannot_be_decrypted_fails_closed(ai, app, monkeypatch):
    set_key(ai)
    with connect(app.config["APP_CONFIG"].database_path, autocommit=True) as conn:         # what a rotated SESSION_SECRET leaves behind
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
    rows = state(ai, project)["images"]
    assert [r["id"] for r in rows] == [second.get_json()["id"]]


@pytest.mark.parametrize("data", [b"not an image", b"GIF89a" + b"\x00" * 40, b""])
def test_something_that_is_not_a_photo_is_refused(ai, project, data):
    assert photo(ai, project["id"], data).status_code == 400


def test_a_photo_for_a_missing_calculation(ai):
    assert photo(ai, "00000000-0000-0000-0000-000000000000").status_code == 404


# --- generating ---------------------------------------------------------------------------------------------------------

def state(owner, project):
    return owner.get(f"/api/projects/{project['id']}/images").get_json()


def queue(owner, project, *variants, **extra):
    return post(owner, f"/api/projects/{project['id']}/images/generate", {"variants": list(variants), **extra} if variants else extra)


def log(owner, lang="nl"):
    return owner.get("/api/ai-images/log", headers={"X-Lang": lang}).get_json()


def ready(owner, project, monkeypatch, **fake_args):
    set_key(owner)
    photo(owner, project["id"])
    return FakeOpenAI(monkeypatch, **fake_args)


def test_asking_for_pictures_answers_at_once_and_they_are_made_in_the_background(ai, project, monkeypatch, app):
    fake = ready(ai, project, monkeypatch)
    threads = []
    monkeypatch.setattr(ai_images, "_start", lambda *a: threads.append(REAL_START(*a)) or threads[-1])
    res = queue(ai, project, "square", "studio")
    assert res.status_code == 202
    assert [(j["variant"], j["status"]) for j in res.get_json()["jobs"]] == [("square", "queued"), ("studio", "queued")]
    threads[0].join(20)
    assert not threads[0].is_alive() and len(fake.calls) == 2
    got = state(ai, project)
    assert [i["variant"] for i in got["images"] if i["kind"] == "generated"] == ["square", "studio"]
    assert [j["status"] for j in got["jobs"]] == ["done", "done"]                  # the page counts them: "2 of 2"
    messages = [e["message"] for e in log(ai, "en")]
    assert "2 images queued." in messages and messages.count("Image started.") == 2 and sum(m.startswith("Image finished") for m in messages) == 2


def test_the_request_to_openai(ai, project, monkeypatch):
    fake = ready(ai, project, monkeypatch)
    res = queue(ai, project, "landscape")
    assert res.status_code == 202
    call = fake.calls[0]
    assert (call["method"], call["url"]) == ("POST", "https://api.openai.com/v1/images/edits")
    assert call["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert call["data"]["model"] == "gpt-image-2" and call["data"]["size"] == "1536x1024" and call["data"]["quality"] == "medium"
    assert "plantenbak voor op een vensterbank" in call["data"]["prompt"]
    name, content, mime = call["files"]["image"]
    assert mime == "image/jpeg" and Image.open(BytesIO(content)).size == (300, 200)
    made = [i for i in state(ai, project)["images"] if i["kind"] == "generated"]
    assert len(made) == 1 and made[0]["variant"] == "landscape"
    assert Image.open(BytesIO(ai.get(f"/api/project-images/{made[0]['id']}/file").data)).size == (64, 64)


def test_all_four_variants_are_made_by_default(ai, project, monkeypatch):
    fake = ready(ai, project, monkeypatch)
    assert queue(ai, project).status_code == 202
    assert [c["data"]["size"] for c in fake.calls] == ["1024x1024", "1536x1024", "1024x1536", "1024x1024"]


def test_a_description_from_the_form_wins_over_the_saved_one(ai, project, monkeypatch):
    fake = ready(ai, project, monkeypatch)
    queue(ai, project, "square", description="sleutelhanger")
    assert "sleutelhanger" in fake.calls[0]["data"]["prompt"] and "plantenbak" not in fake.calls[0]["data"]["prompt"]
    assert queue(ai, project, "square", description="x" * 501).status_code == 400


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
    assert queue(ai, project, "square").status_code == 400                         # no key
    set_key(ai)
    assert queue(ai, project, "square").status_code == 400                         # no photo
    photo(ai, project["id"])
    for bad in (["wide"], [], "square", ["square", "square"]):
        assert post(ai, f"/api/projects/{project['id']}/images/generate", {"variants": bad}).status_code == 400
    assert not fake.calls and state(ai, project)["jobs"] == []
    assert len([e for e in log(ai) if e["level"] == "error"]) == 6                 # every refusal is in the log: no key, no photo, four bad asks


@pytest.mark.parametrize("status,error,key", [
    (401, '{"code": "invalid_api_key", "message": "Incorrect API key provided: sk-test-0123****mnop"}', "ai.err_key_invalid"),
    (429, '{"code": "insufficient_quota"}', "ai.err_quota"),
    (429, '{"code": "rate_limit_exceeded"}', "ai.err_busy"),
    (400, '{"code": "moderation_blocked", "message": "no"}', "ai.err_policy"),
    (400, '{"message": "Invalid size"}', "ai.err_rejected"),
    (404, '{"message": "model not found"}', "ai.err_model_unknown"),
    (503, '{}', "ai.err_upstream"),
])
def test_what_openai_refuses_ends_up_on_the_job_and_in_the_log(ai, project, monkeypatch, status, error, key):
    ready(ai, project, monkeypatch, status=status, error=error)
    res = queue(ai, project, "square")
    assert res.status_code == 202                                                  # it was queued; the failure is what the job says
    got = state(ai, project)
    assert [i["kind"] for i in got["images"]] == ["source"]                         # nothing was stored
    assert [j["status"] for j in got["jobs"]] == ["failed"] and got["jobs"][0]["message"]
    errors = [e for e in log(ai) if e["level"] == "error"]
    assert len(errors) == 1 and errors[0]["variant"] == "square" and errors[0]["project_number"] == project["number"]
    assert errors[0]["message"] == got["jobs"][0]["message"] and errors[0]["detail"].startswith(f"HTTP {status}")
    everything = json.dumps([got, log(ai)])
    assert KEY not in everything and "sk-test-0123" not in everything            # not even the piece OpenAI quotes


def test_the_message_and_the_log_follow_the_language(ai, project, monkeypatch):
    ready(ai, project, monkeypatch, status=400, error='{"message": "Invalid size 9x9"}')
    queue(ai, project, "square")
    jobs = ai.get(f"/api/projects/{project['id']}/images", headers={"X-Lang": "en"}).get_json()["jobs"]
    assert "Invalid size 9x9" in jobs[0]["message"] and jobs[0]["message"].startswith("OpenAI refused")
    assert log(ai, "nl")[0]["message"].startswith("OpenAI weigerde") and log(ai, "en")[0]["message"].startswith("OpenAI refused")


def test_a_problem_with_the_key_gives_up_the_rest_but_other_problems_do_not(ai, project, monkeypatch):
    fake = ready(ai, project, monkeypatch, status=401, error='{"code": "invalid_api_key"}')
    queue(ai, project)
    assert len(fake.calls) == 1                                                    # the other three would fail the same way
    assert [j["status"] for j in state(ai, project)["jobs"]] == ["failed"] * 4
    assert len([e for e in log(ai) if e["level"] == "error"]) == 4

    FakeOpenAI(monkeypatch, raises=requests.Timeout())
    queue(ai, project)
    assert [j["message"] is not None for j in state(ai, project)["jobs"]] == [True] * 4
    assert len(ai_images.requests.request.calls) == 4                              # a timeout is tried again for the next picture


def test_a_connection_problem_is_not_a_reason_to_stop(ai, project, monkeypatch):
    fake = ready(ai, project, monkeypatch, raises=requests.ConnectionError())
    queue(ai, project)
    assert len(fake.calls) == 4 and [j["status"] for j in state(ai, project)["jobs"]] == ["failed"] * 4


def test_an_answer_that_is_no_image_is_a_failed_job(ai, project, monkeypatch):
    ready(ai, project, monkeypatch, result=b"this is not an image")
    queue(ai, project, "square")
    assert state(ai, project)["jobs"][0]["status"] == "failed"
    assert [e["detail"] for e in log(ai) if e["level"] == "error"] == ["no usable image in the answer"]


def test_an_unexpected_crash_is_a_failed_job_too(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    monkeypatch.setattr(ai_images, "_generate", lambda *a, **k: 1 / 0)
    queue(ai, project, "square")
    assert state(ai, project)["jobs"][0]["status"] == "failed"
    assert log(ai)[0]["message"].startswith("Er ging iets mis")


def test_only_one_batch_at_a_time_per_calculation_and_the_page_can_ask_again_later(ai, project, monkeypatch, app):
    ready(ai, project, monkeypatch)
    monkeypatch.setattr(ai_images, "_start", lambda *a: None)                      # the thread has not got to it yet
    assert queue(ai, project, "square").status_code == 202
    assert queue(ai, project, "studio").status_code == 409
    assert [j["status"] for j in state(ai, project)["jobs"]] == ["queued"]         # what a page sees when it comes back
    assert [p["ai_busy"] for p in ai.get("/api/projects").get_json()] == [True]
    # the thread of a restarted container never comes back: after a while the job is given up, not shown as busy for ever
    with connect(app.config["APP_CONFIG"].database_path, autocommit=True) as conn:
        conn.execute("UPDATE ai_image_jobs SET updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now', '-6 minutes')")
    got = state(ai, project)
    assert [j["status"] for j in got["jobs"]] == ["failed"] and "onderbroken" in got["jobs"][0]["message"]
    assert [p["ai_busy"] for p in ai.get("/api/projects").get_json()] == [False]
    assert any(e["level"] == "error" and "onderbroken" in e["message"] for e in log(ai))
    assert queue(ai, project, "studio").status_code == 202                         # and it can be asked again


def test_a_job_that_is_still_moving_is_left_alone(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    monkeypatch.setattr(ai_images, "_start", lambda *a: None)
    queue(ai, project, "square")
    assert [j["status"] for j in state(ai, project)["jobs"]] == ["queued"]


def test_finished_pictures_do_not_block_the_next_batch_and_are_cleared_with_it(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    queue(ai, project, "square")
    assert [j["status"] for j in state(ai, project)["jobs"]] == ["done"]
    monkeypatch.setattr(ai_images, "_start", lambda *a: None)
    queue(ai, project, "studio")
    assert [(j["variant"], j["status"]) for j in state(ai, project)["jobs"]] == [("studio", "queued")]


def test_failed_messages_can_be_dismissed(ai, project, monkeypatch):
    ready(ai, project, monkeypatch, status=400, error='{"message": "x"}')
    queue(ai, project, "square")
    assert len(state(ai, project)["jobs"]) == 1
    assert ai.delete(f"/api/projects/{project['id']}/images/jobs", headers=H).status_code == 200
    assert state(ai, project)["jobs"] == [] and len(log(ai)) >= 2                  # the log keeps them


def test_deleting_the_calculation_while_pictures_are_queued_stops_quietly(ai, project, monkeypatch, app):
    fake = ready(ai, project, monkeypatch)
    batches = []
    monkeypatch.setattr(ai_images, "_start", lambda a, p, b: batches.append((p, b)))
    queue(ai, project)
    ai.delete(f"/api/projects/{project['id']}", headers=H)
    ai_images._run_batch(app, *batches[0])                                         # the thread wakes up to nothing
    assert not fake.calls
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        assert conn.execute("SELECT count(*) FROM ai_image_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM project_images").fetchone()[0] == 0


def test_the_number_of_pictures_is_capped(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    for _ in range(ai_images.MAX_GENERATED // 4):
        assert queue(ai, project).status_code == 202
    assert queue(ai, project, "studio").status_code == 409
    assert len([i for i in state(ai, project)["images"] if i["kind"] == "generated"]) == ai_images.MAX_GENERATED


def test_generating_is_rate_limited(ai, project, monkeypatch):
    fake = ready(ai, project, monkeypatch)
    monkeypatch.setattr(ai_images, "_limit", ai_images.RateLimiter(5, 3600))
    assert queue(ai, project).status_code == 202                                   # four of five
    assert queue(ai, project, "studio", "square").status_code == 429               # would be six
    assert len(fake.calls) == 4 and [j["status"] for j in state(ai, project)["jobs"]] == ["done"] * 4      # nothing new was queued


# --- the log ----------------------------------------------------------------------------------------------------------------

def test_the_log_tells_what_happened_newest_first(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    queue(ai, project, "square")
    entries = log(ai, "en")
    messages = [e["message"] for e in entries]
    assert messages[0].startswith("Image finished after ") and messages[1:] == ["Image started.", "1 images queued.",
                                                                              "Photo of the object uploaded.", "An API key was saved."]
    assert {e["level"] for e in entries} == {"info"} and entries[0]["variant"] == "square"
    assert entries[0]["project_id"] == project["id"] and entries[0]["project_number"] == project["number"] and entries[0]["project_name"]
    assert [e["message"] for e in log(ai, "nl")][-1] == "Een API-sleutel is opgeslagen."


def test_settings_and_the_connection_test_are_in_the_log_without_the_key(ai, monkeypatch):
    set_key(ai)
    ai.put("/api/ai-images/settings", json={"model": "gpt-image-2-mini", "quality": "high"}, headers=H)
    ai.put("/api/ai-images/settings", json={"quality": "high"}, headers=H)          # nothing changed: nothing logged
    FakeOpenAI(monkeypatch)
    post(ai, "/api/ai-images/test")
    FakeOpenAI(monkeypatch, status=401, error='{"code": "invalid_api_key", "message": "Incorrect API key provided: %s"}' % KEY)
    assert post(ai, "/api/ai-images/test").status_code == 400
    ai.delete("/api/ai-images/key", headers=H)
    ai.delete("/api/ai-images/key", headers=H)                                      # no key left: nothing logged
    assert post(ai, "/api/ai-images/test").status_code == 400                       # no key
    entries = log(ai, "en")
    assert [e["message"] for e in entries][::-1][:3] == ["An API key was saved.", "Settings changed: model gpt-image-2-mini, quality high.",
                                                       "Connection test succeeded (model gpt-image-2-mini)."]
    assert [e["level"] for e in entries].count("error") == 2 and [e["message"] for e in entries].count("The API key was removed.") == 1
    assert KEY not in json.dumps(entries)
    failing = [e for e in entries if e["detail"]][0]
    assert failing["detail"].startswith("HTTP 401 invalid_api_key") and failing["project_id"] is None


def test_a_refused_photo_is_in_the_log(ai, project):
    assert photo(ai, project["id"], b"not an image").status_code == 400
    assert log(ai, "en")[0]["level"] == "error" and "JPEG, PNG or WebP" in log(ai, "en")[0]["message"]


def test_the_log_keeps_the_latest_lines_and_can_be_cleared(ai, monkeypatch):
    monkeypatch.setattr(ai_images, "LOG_KEEP", 5)
    for _ in range(8):
        ai.put("/api/ai-images/settings", json={"api_key": KEY + str(_)}, headers=H)
    assert len(log(ai)) == 5
    assert ai.delete("/api/ai-images/log", headers=H).status_code == 200
    assert [e["message"] for e in log(ai, "en")] == ["The log was cleared."]


def test_the_log_is_not_in_a_backup(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    queue(ai, project, "square")
    doc = backup(ai).get_json()
    assert not [k for k in doc if "log" in k or "job" in k]


def test_the_log_needs_the_flag_and_a_session(app, client):
    assert client.get("/api/ai-images/log").status_code == 401
    onboard(client)
    assert client.get("/api/ai-images/log").status_code == 404 and client.delete("/api/ai-images/log", headers=H).status_code == 404


# --- using the pictures -----------------------------------------------------------------------------------------------

def test_cover_download_and_delete(ai, project, monkeypatch):
    ready(ai, project, monkeypatch)
    queue(ai, project, "square", "studio")
    made = {i["variant"]: i for i in state(ai, project)["images"] if i["kind"] == "generated"}
    first, second = made["square"], made["studio"]
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
    with connect(app.config["APP_CONFIG"].database_path) as conn:
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
    ready(ai, project, monkeypatch)
    ai.put("/api/ai-images/settings", json={"model": "gpt-image-2-mini", "quality": "low"}, headers=H)
    queue(ai, project, "portrait")
    made = [i for i in state(ai, project)["images"] if i["kind"] == "generated"][0]
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
    images = state(ai, project)["images"]
    assert [(i["kind"], i["variant"], i["is_cover"]) for i in images] == [("source", None, False), ("generated", "portrait", True)]
    assert ai.get("/api/projects").get_json()[0]["cover_image_id"] == images[1]["id"]
    assert ai.get("/api/ai-images/settings").get_json()["model"] == "gpt-image-2-mini"
    assert ai.get("/api/ai-images/settings").get_json()["last4"] == KEY[-4:]                    # the key was not touched by the restore


def test_a_backup_with_a_damaged_picture_is_refused_before_anything_changes(ai, project):
    photo(ai, project["id"])
    doc = backup(ai).get_json()
    doc["project_images"][0]["content_b64"] = base64.b64encode(b"not an image").decode()
    assert post(ai, "/api/backup/restore", doc).status_code == 400
    assert len(state(ai, project)["images"]) == 1
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
