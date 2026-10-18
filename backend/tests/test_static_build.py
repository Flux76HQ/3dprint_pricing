"""Every script the server hands out belongs to one release, and the page knows which one it loaded.

Reported: the sidebar said the newest version while the password option was missing. The label came from the
server's answer, not from the code that was running, so an old script cache looked up to date."""
import re
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.db import run_migrations
from tests.conftest import ORIGIN, RP_ID, SECRET, SETUP_CODE

FRONT = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture
def real(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "0123456789")
    run_migrations(fresh_db)
    cfg = Config(database_url=fresh_db, session_secret=SECRET, setup_code=SETUP_CODE, rp_id=RP_ID, rp_name="Test",
                 rp_origins=(ORIGIN,), session_hours=24, cookie_secure=True, upload_dir=str(tmp_path / "up"),
                 static_dir=str(FRONT))
    app = create_app(cfg)
    yield app.test_client()
    app.extensions["pool"].close()


def test_every_import_and_the_entry_scripts_carry_the_release(real):
    token = re.compile(r"\?v=[\w.]+-0123456")
    index = real.get("/").get_data(as_text=True)
    assert 'src="/js/main.js?v=' in index and 'href="/css/app.css?v=' in index and token.search(index)
    # iOS keeps a home-screen icon (or the failure to get one) per URL, so the icon URL changes with every release
    assert re.search(r'rel="apple-touch-icon" href="/icons/apple-touch-icon\.png\?v=[\w.]+-0123456\.[0-9a-f]+"', index)
    assert re.search(r'rel="icon" type="image/png" sizes="32x32" href="/icons/favicon-32\.png\?v=', index)
    assert "/splash/splash-" in index and "splash.png?v=" not in index and "icon.svg?v=" not in index
    for script in sorted((FRONT / "js").glob("*.js")):
        served = real.get(f"/js/{script.name}")
        assert served.status_code == 200 and "no-cache" in served.headers["Cache-Control"]
        text = served.get_data(as_text=True)
        for specifier in re.findall(r"""from\s+['"](\./[^'"]+)['"]""", text):
            assert token.search(specifier), f"{script.name} imports {specifier} without the release"


def test_the_page_learns_what_it_loaded_from_the_file_itself(real):
    build = real.get("/js/build.js").get_data(as_text=True)
    assert re.search(r"BUILD = \{ version: '[^']+', commit: '0123456' \}", build) and "'dev', commit: 'dev'" not in build


def test_the_sidebar_and_the_update_check_use_the_built_in_release_not_the_servers_answer():
    main = (FRONT / "js/main.js").read_text()
    assert "initUpdates(BUILD)" in main and "api('GET', '/api/version')" not in main


def test_stamped_files_are_still_revalidated_cheaply(real):
    first = real.get("/js/main.js")
    assert real.get("/js/main.js", headers={"If-None-Match": first.headers["ETag"]}).status_code == 304
    assert real.get("/vendor/zxing/zxing-library.min.js").status_code == 200          # vendor files are not rewritten


def test_the_release_is_part_of_the_urls_so_a_new_release_cannot_reuse_old_ones(real, monkeypatch):
    old = real.get("/js/main.js").get_data(as_text=True)
    monkeypatch.setenv("APP_COMMIT", "fedcba9876")
    new = real.get("/js/main.js").get_data(as_text=True)
    assert old != new and "-fedcba9" in new and "-0123456" not in new


def test_the_home_screen_icon_has_a_new_url_on_every_load(real, monkeypatch):
    pattern = re.compile(r'rel="apple-touch-icon" href="(/icons/apple-touch-icon\.png\?v=[^"]+)"')
    ticks = iter(range(1_700_000_000_000_000_000, 1_700_000_000_000_000_000 + 10 ** 10, 10 ** 7))
    monkeypatch.setattr("app.time.time_ns", lambda: next(ticks))
    first = pattern.search(real.get("/").get_data(as_text=True)).group(1)
    second = pattern.search(real.get("/").get_data(as_text=True)).group(1)
    assert first != second
    for url in (first, second):                                                          # whatever the query says, it is the icon
        served = real.get(url)
        assert served.status_code == 200 and served.mimetype == "image/png" and "no-cache" in served.headers["Cache-Control"]
