"""Every script the server hands out belongs to one release, and the page knows which one it loaded.

Reported: the sidebar said the newest version while the password option was missing. The label came from the
server's answer, not from the code that was running, so an old script cache looked up to date.

Because the release is in the URL, a URL of the running release is kept by the browser without asking again (`immutable`), and only that:
the page, the worker, a plain URL, another release's URL and a development build are checked with the server every time
(`app/static_files.py`). The files are stamped and compressed once per process. Numbers: docs/performance.md."""
import gzip
import re
from pathlib import Path

import pytest

from app import create_app, static_files
from app.config import Config
from app.db import run_migrations
from tests.conftest import ORIGIN, RP_ID, SECRET, SETUP_CODE

FRONT = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture
def real(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "0123456789")
    run_migrations(fresh_db)
    cfg = Config(database_path=fresh_db, session_secret=SECRET, setup_code=SETUP_CODE, rp_id=RP_ID, rp_name="Test",
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


def test_the_page_may_use_the_camera_for_scanning_but_nothing_else_may(real):
    """The barcode scanner needs the camera of this origin; `camera=()` made Chrome and Android refuse it (Safari ignores the header)."""
    policy = {name: value for name, value in (part.strip().split("=", 1) for part in real.get("/").headers["Permissions-Policy"].split(","))}
    assert policy == {"camera": "(self)", "microphone": "()", "geolocation": "()"}
    assert real.get("/").headers["X-Frame-Options"] == "DENY"                       # no other page can borrow it by framing this one


def test_the_page_learns_what_it_loaded_from_the_file_itself(real):
    build = real.get("/js/build.js").get_data(as_text=True)
    assert re.search(r"BUILD = \{ version: '[^']+', commit: '0123456', channel: 'stable' \}", build) and "'dev', commit: 'dev'" not in build


def test_a_stable_build_has_no_beta_label(real):
    assert real.get("/api/version").get_json()["channel"] == "stable"
    assert "channel: 'stable'" in real.get("/js/build.js").get_data(as_text=True)
    index = real.get("/").get_data(as_text=True)
    assert "<title>3D Print Pricing</title>" in index and 'content="PrintPricing"' in index


@pytest.mark.parametrize("tag, channel", [("beta", "beta"), ("2.0.0-beta", "beta"), ("latest", "stable"), ("0.26.15", "stable"), ("", "stable")])
def test_the_tag_decides_the_channel(real, monkeypatch, tag, channel):
    monkeypatch.setenv("PRINTPRICING_TAG", tag)
    assert real.get("/api/version").get_json()["channel"] == channel
    assert f"channel: '{channel}'" in real.get("/js/build.js").get_data(as_text=True)


def test_a_beta_build_says_so_in_the_tab_title_and_under_the_home_screen_icon(real, monkeypatch):
    monkeypatch.setenv("PRINTPRICING_TAG", "beta")
    index = real.get("/").get_data(as_text=True)
    assert "<title>3D Print Pricing (beta)</title>" in index and 'content="PrintPricing beta"' in index


def test_the_beta_label_is_drawn_next_to_the_name_in_the_sidebar_and_on_the_login_screen():
    assert "betaBadge()" in (FRONT / "js/main.js").read_text() and "betaBadge()" in (FRONT / "js/auth-views.js").read_text()


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
    monkeypatch.setattr("app.static_files.time.time_ns", lambda: next(ticks))
    first = pattern.search(real.get("/").get_data(as_text=True)).group(1)
    second = pattern.search(real.get("/").get_data(as_text=True)).group(1)
    assert first != second
    for url in (first, second):                                                          # whatever the query says, it is the icon
        served = real.get(url)
        assert served.status_code == 200 and served.mimetype == "image/png" and "no-cache" in served.headers["Cache-Control"]


# --- kept by the browser, compressed, stamped once (docs/performance.md) ------------------------------------------------------------

KEPT = "public, max-age=31536000, immutable"
RELEASE_FILES = ("/js/main.js", "/js/theme-boot.js", "/css/app.css", "/icons/favicon-32.png", "/lang/nl.json", "/lang/en.json")


def release(client) -> str:
    """The `?v=` the page itself asks for its scripts with."""
    return re.search(r'src="/js/main\.js\?v=([^"]+)"', client.get("/").get_data(as_text=True)).group(1)


def test_a_url_of_the_running_release_is_kept_without_asking_again(real):
    token = release(real)
    for path in RELEASE_FILES:
        served = real.get(f"{path}?v={token}")
        assert served.status_code == 200 and served.headers["Cache-Control"] == KEPT, path


def test_the_page_asks_for_the_language_files_with_the_release_too():
    assert "/lang/${code}.json?v=${BUILD.version}-${BUILD.commit}" in (FRONT / "js/i18n.js").read_text()


def test_only_a_url_of_the_running_release_is_kept(real):
    """Another release's URL is what an app asks for that stayed open during an update: the file the server has now is not the one that URL
    meant, so it must not be kept under it. The home screen icon's URL is new on every load and would fill the cache."""
    token = release(real)
    for query in ("", "?v=0.0.1-abcdef0", f"?v={token}x", f"?v={token}.18c1f", "?v="):
        for path in RELEASE_FILES:
            assert real.get(path + query).headers["Cache-Control"] == "no-cache", path + query


def test_the_page_and_the_worker_are_checked_with_the_server_every_time(real):
    """They are how a new release is noticed, so no URL makes them kept."""
    token = release(real)
    for path in ("/", "/index.html", "/berekeningen", "/sw.js"):
        for query in ("", f"?v={token}"):
            served = real.get(path + query)
            assert served.status_code == 200 and served.headers["Cache-Control"] == "no-cache", path + query
    assert real.get("/index.html").get_data(as_text=True).count(f"?v={token}") >= 4               # the page by its file name is the same stamped page


def test_a_development_build_is_never_kept(real, monkeypatch):
    """Without a commit every build has the same name while its files change."""
    monkeypatch.setenv("APP_COMMIT", "dev")
    token = release(real)
    assert token.endswith("-dev")
    for path in RELEASE_FILES:
        assert real.get(f"{path}?v={token}").headers["Cache-Control"] == "no-cache", path
    monkeypatch.delenv("APP_COMMIT")
    assert real.get(f"/js/main.js?v={release(real)}").headers["Cache-Control"] == "no-cache"


def test_a_file_is_stamped_and_compressed_once_and_not_on_every_request(real, monkeypatch):
    work = {"stamped": 0, "packed": 0}
    stamp, pack = static_files.stamped, static_files.packed

    def counted(name, original):
        def run(*args):
            work[name] += 1
            return original(*args)
        return run

    monkeypatch.setattr(static_files, "stamped", counted("stamped", stamp))
    monkeypatch.setattr(static_files, "packed", counted("packed", pack))
    answers = {real.get("/js/main.js", headers={"Accept-Encoding": "gzip"}).data for _ in range(5)}
    assert len(answers) == 1 and work == {"stamped": 1, "packed": 1}
    real.get("/sw.js"), real.get("/sw.js"), real.get("/css/app.css"), real.get("/css/app.css")
    assert work == {"stamped": 3, "packed": 3}
    for _ in range(3):                                                # the page: stamped once; only the icon's URL is new each time
        real.get("/")
    assert work["stamped"] == 4
    monkeypatch.setenv("APP_COMMIT", "fedcba9876")                    # another build is never answered from what was kept for this one
    assert "-fedcba9" in real.get("/js/main.js").get_data(as_text=True) and work["stamped"] == 5


def test_a_changed_file_is_read_again(tmp_path):
    """What is kept in memory is checked against the file, so editing a file while developing shows at the next request."""
    (tmp_path / "js").mkdir()
    (tmp_path / "js/a.js").write_text("import { b } from './b.js';\n")
    assets, build = static_files.Assets(str(tmp_path)), static_files.Build("1.2.3", "abc1234", "stable")
    first = assets.text("js/a.js", build)
    assert first.body == b"import { b } from './b.js?v=1.2.3-abc1234';\n" and assets.text("js/a.js", build) is first
    (tmp_path / "js/a.js").write_text("import { b, c } from './b.js';\n")
    assert assets.text("js/a.js", build).body == b"import { b, c } from './b.js?v=1.2.3-abc1234';\n"


def test_text_is_sent_compressed_to_a_browser_that_reads_gzip(real):
    token = release(real)
    for path in ("/", "/sw.js", "/js/settings.js", f"/js/settings.js?v={token}", "/css/app.css", "/lang/nl.json", "/manifest.webmanifest",
                 "/vendor/zxing/zxing-library.min.js"):
        plain, zipped = real.get(path), real.get(path, headers={"Accept-Encoding": "gzip, deflate, br"})
        assert "Content-Encoding" not in plain.headers and zipped.headers["Content-Encoding"] == "gzip", path
        assert plain.headers["Vary"] == zipped.headers["Vary"] == "Accept-Encoding", path          # a cache in between keeps the two apart
        assert plain.headers["Cache-Control"] == zipped.headers["Cache-Control"] and plain.mimetype == zipped.mimetype
        if path != "/":                                                                           # (the page differs per load: the icon's URL)
            assert gzip.decompress(zipped.data) == plain.data and len(zipped.data) < len(plain.data) * 0.6, path
            assert plain.headers["ETag"] != zipped.headers["ETag"]                                # different bytes, different validators
            for answer, accept in ((plain, "identity"), (zipped, "gzip")):
                assert real.get(path, headers={"Accept-Encoding": accept, "If-None-Match": answer.headers["ETag"]}).status_code == 304
    icon = real.get("/icons/favicon-32.png", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in icon.headers and icon.data.startswith(b"\x89PNG")            # an image is compressed already


def test_no_address_reaches_a_file_outside_the_static_folder(real):
    """`backend/requirements.txt` is next to `frontend/`: a path with `..` in it must not find it (text files are read by the app itself)."""
    for path in ("/js/../../backend/requirements.txt", "/lang/../../backend/requirements.txt", "/css/../../README.md", "/js/../../backend/wsgi.js",
                 "/vendor/../../VERSION.txt"):
        served = real.get(path)
        assert b"flask==" not in served.data and b"# 3D Print Pricing" not in served.data, path
        assert served.status_code == 404 or served.mimetype == "text/html", path
    assert static_files.Assets(str(FRONT)).path("../backend/requirements.txt") is None
    assert static_files.Assets(str(FRONT)).path("js/../../backend/requirements.txt") is None
    assert static_files.Assets(str(FRONT)).path("js/main.js") == FRONT / "js/main.js"


def test_the_worker_caches_every_module_of_the_release_and_nothing_that_is_gone():
    """The installed app starts from the worker's cache, so a module that is not in its list is fetched at every launch, and one that
    no longer exists makes the install of the worker fail."""
    source = (FRONT / "sw.js").read_text(encoding="utf-8")
    shell = set(re.findall(r"'(/(?:js|css|lang)/[^']+)'", source[source.index("const SHELL"):source.index("const versioned")]))
    on_disk = {f"/js/{path.name}" for path in (FRONT / "js").glob("*.js")} | {f"/lang/{path.name}" for path in (FRONT / "lang").glob("*.json")} | {"/css/app.css"}
    assert shell == on_disk
