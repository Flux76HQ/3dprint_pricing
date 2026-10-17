import io
import os

import pytest

from tests import printfiles as pf
from tests.test_auth_api import H, onboard, post
from tests.test_domain_api import make, sheet_payload


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def upload(client, data, name="part.stl"):
    return client.post("/api/print-files", data={"file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data", headers=H)


def test_upload_reads_the_file_and_stores_it(owner, app):
    res = upload(owner, pf.sliced_3mf(), "USW rack-mount.gcode.3mf")
    assert res.status_code == 201
    body = res.get_json()
    assert body["kind"] == "3mf" and body["analysis"]["exact"] is True
    assert body["analysis"]["plates"][0]["grams"] == 35.3
    stored = os.listdir(app.config["APP_CONFIG"].upload_dir)
    assert len(stored) == 1 and stored[0].endswith(".3mf") and not stored[0].startswith(".tmp")
    again = owner.get(f"/api/print-files/{body['id']}").get_json()
    assert again["filename"] == "USW rack-mount.gcode.3mf"


def test_download_returns_the_original_bytes(owner):
    data = pf.stl_binary()
    fid = upload(owner, data).get_json()["id"]
    res = owner.get(f"/api/print-files/{fid}/download")
    assert res.status_code == 200 and res.data == data
    assert "attachment" in res.headers["Content-Disposition"] and "part.stl" in res.headers["Content-Disposition"]


def test_rejected_uploads_leave_nothing_behind(owner, app):
    assert upload(owner, b"not a model", "x.stl").status_code == 400
    assert upload(owner, b"", "x.stl").status_code == 400
    assert upload(owner, b"x", "x.exe").status_code == 400
    assert owner.post("/api/print-files", data={}, content_type="multipart/form-data", headers=H).status_code == 400
    assert os.listdir(app.config["APP_CONFIG"].upload_dir) == []


def test_filenames_cannot_escape_the_upload_dir(owner, app):
    res = upload(owner, pf.stl_binary(), "../../etc/passwd.stl")
    assert res.status_code == 201 and res.get_json()["filename"] == "passwd.stl"
    assert all(os.sep not in n for n in os.listdir(app.config["APP_CONFIG"].upload_dir))


def test_oversized_upload_is_refused_with_a_dutch_message(owner):
    res = upload(owner, b"\0" * (3 * 1024 * 1024), "big.stl")     # test config allows 2 MB
    assert res.status_code == 413 and "2 MB" in res.get_json()["error"]


def test_files_need_a_session(client):
    assert client.get("/api/print-files/materials").status_code == 401
    res = client.post("/api/print-files", data={"file": (io.BytesIO(b"x"), "a.stl")},
                      content_type="multipart/form-data", headers=H)
    assert res.status_code == 401


def test_estimate_uses_density_and_fill(owner):
    fid = upload(owner, pf.stl_binary(scale=3)).get_json()["id"]      # 27 cm3
    res = owner.get(f"/api/print-files/{fid}/estimate?density=1.24&fill=40").get_json()
    assert res["grams"] == 13.4
    assert owner.get(f"/api/print-files/{fid}/estimate?density=9&fill=40").status_code == 400
    assert owner.get(f"/api/print-files/{fid}/estimate?density=abc").status_code == 400
    assert "ABS" in owner.get("/api/print-files/materials").get_json()


def test_project_links_the_file_and_a_source_url(owner):
    fid = upload(owner, pf.sliced_3mf(), "print.3mf").get_json()["id"]
    body = {**sheet_payload(), "file_id": fid, "source_url": "https://makerworld.com/en/models/12345"}
    p = make(owner, "/api/projects", body)
    assert p["file_id"] == fid and p["source_url"].startswith("https://makerworld.com/")
    again = owner.get(f"/api/projects/{p['id']}").get_json()
    assert again["file_id"] == fid
    unlinked = owner.put(f"/api/projects/{p['id']}", json={**sheet_payload(), "source_url": ""}, headers=H)
    assert unlinked.get_json()["file_id"] is None and unlinked.get_json()["source_url"] == ""


@pytest.mark.parametrize("extra", [{"file_id": "00000000-0000-0000-0000-000000000000"}, {"file_id": "nope"},
                                   {"source_url": "javascript:alert(1)"}, {"source_url": "ftp://x/y"}])
def test_project_rejects_bad_links(owner, extra):
    assert owner.post("/api/projects", json={**sheet_payload(), **extra}, headers=H).status_code == 400


def test_unlinked_uploads_are_purged_after_a_day_but_linked_ones_stay(owner, app):
    import psycopg
    kept = upload(owner, pf.stl_binary(), "kept.stl").get_json()["id"]
    make(owner, "/api/projects", {**sheet_payload(), "file_id": kept})
    orphan = upload(owner, pf.stl_binary(), "orphan.stl").get_json()["id"]
    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        conn.execute("UPDATE print_files SET created_at = now() - interval '2 days'")
    upload(owner, pf.stl_binary(), "trigger.stl")           # any upload runs the cleanup
    assert owner.get(f"/api/print-files/{kept}").status_code == 200
    assert owner.get(f"/api/print-files/{orphan}").status_code == 404
    assert len(os.listdir(app.config["APP_CONFIG"].upload_dir)) == 2   # kept + trigger


def test_packaging_flows_through_the_api(owner):
    body = sheet_payload()
    body["data"]["parts"] = [{"group": "verpakking", "label": "Doos", "quantity": 1, "unit": "stuks", "unit_price": "0.85"}]
    res = owner.post("/api/calculate", json=body, headers=H).get_json()
    assert res["subtotals"]["packaging"] == "0.85" and res["cost_price"] == "3.59"
