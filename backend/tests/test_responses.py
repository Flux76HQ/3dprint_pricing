"""What an answer of the API says about keeping and compressing it: nothing is kept (prices must be live), and a JSON answer
is gzipped for a browser that reads gzip (`http.compressed`), because nothing in front of the app is certain to do it. The app's own
files are in test_static_build.py, the one kind of answer a browser may keep in test_ai_images.py. Numbers: docs/performance.md."""
import gzip
import io
import json

import pytest

from tests import printfiles as pf
from tests.test_auth_api import H, onboard
from tests.test_domain_api import make


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def printers(owner, count):
    for n in range(count):
        make(owner, "/api/printers", {"name": f"Printer {n}", "purchase_price": "699", "lifetime_hours": "5000", "power_kw": "0.11"})


def test_a_list_is_compressed_for_a_browser_that_reads_gzip(owner):
    printers(owner, 12)
    plain, zipped = owner.get("/api/printers"), owner.get("/api/printers", headers={"Accept-Encoding": "gzip, deflate, br"})
    assert "Content-Encoding" not in plain.headers and len(plain.data) > 2000
    assert zipped.headers["Content-Encoding"] == "gzip" and "Accept-Encoding" in zipped.headers["Vary"]
    assert json.loads(gzip.decompress(zipped.data)) == plain.get_json() and len(zipped.data) < len(plain.data) / 3
    assert int(zipped.headers["Content-Length"]) == len(zipped.data)
    assert plain.headers["Cache-Control"] == zipped.headers["Cache-Control"] == "no-store"            # compressed or not, never kept


def test_what_is_not_worth_it_is_left_alone(owner):
    reads = {"Accept-Encoding": "gzip"}
    printers(owner, 1)
    short = owner.get("/api/printers", headers=reads)                                                 # a short answer: the header costs more
    assert short.status_code == 200 and "Content-Encoding" not in short.headers and short.get_json()[0]["name"] == "Printer 0"
    assert "Content-Encoding" not in owner.get("/api/printers", headers={"Accept-Encoding": "identity"}).headers
    assert "Content-Encoding" not in owner.get("/api/printers", headers={"Accept-Encoding": "gzip;q=0"}).headers     # says it does not want it
    missing = owner.get("/api/projects/00000000-0000-4000-8000-000000000000", headers=reads)
    assert missing.status_code == 404 and "Content-Encoding" not in missing.headers and missing.get_json()["error"]


def test_a_download_is_neither_compressed_nor_kept(owner):
    data = pf.stl_binary()
    uploaded = owner.post("/api/print-files", data={"file": (io.BytesIO(data), "part.stl")}, content_type="multipart/form-data", headers=H).get_json()
    printers(owner, 12)                                                                               # so the backup is long enough to be a candidate
    for path in (f"/api/print-files/{uploaded['id']}/download", "/api/backup", "/api/backup?files=1"):
        res = owner.get(path, headers={"Accept-Encoding": "gzip"})
        assert res.status_code == 200 and "Content-Encoding" not in res.headers, path
        assert len(res.data) > 2000 or path != "/api/backup", path                                    # (the JSON one is long enough to have been compressed)
        assert res.headers["Cache-Control"] == "no-store", path                                       # Flask's own header for a file is replaced
    assert owner.get(f"/api/print-files/{uploaded['id']}/download").data == data
