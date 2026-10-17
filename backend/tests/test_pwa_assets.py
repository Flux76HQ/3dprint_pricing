"""The installed-app surface: iOS icons, launch images, manifest and the no-zoom viewport.

These are static files, so the failure mode is drift: a launch image that no <link> points at, a link
whose media query does not match the PNG's pixel size, or an icon iOS would paint with a black corner.
"""
import json
import re
from pathlib import Path

from PIL import Image

from tests.test_static_build import real  # noqa: F401  (fixture: the app with the real frontend)

FRONT = Path(__file__).resolve().parents[2] / "frontend"
INDEX = (FRONT / "index.html").read_text(encoding="utf-8")


def links(rel):
    return [dict(re.findall(r'(\w[\w-]*)="([^"]*)"', tag)) for tag in re.findall(rf'<link rel="{rel}"[^>]*>', INDEX)]


def meta(name):
    m = re.search(rf'<meta name="{name}" content="([^"]*)"', INDEX)
    return m.group(1) if m else None


def png(path):
    img = Image.open(FRONT / path.lstrip("/"))
    assert img.format == "PNG"
    return img


def test_viewport_blocks_zoom_and_covers_the_safe_areas():
    viewport = meta("viewport")
    for part in ("maximum-scale=1", "user-scalable=no", "viewport-fit=cover", "width=device-width"):
        assert part in viewport, viewport


def test_installed_app_meta_for_ios():
    assert meta("apple-mobile-web-app-capable") == "yes"
    assert meta("mobile-web-app-capable") == "yes"
    assert meta("apple-mobile-web-app-status-bar-style") == "black-translucent"
    assert meta("apple-mobile-web-app-title")


def test_apple_touch_icons_are_opaque_full_bleed_squares_of_the_declared_size():
    icons = links("apple-touch-icon")
    assert len(icons) == 1 and icons[0]["href"] == "/icons/apple-touch-icon.png" and "sizes" not in icons[0]   # as a known-good PWA does it
    for icon in icons:
        img = png(icon["href"])
        w, h = (int(v) for v in icon.get("sizes", "180x180").split("x"))
        assert img.size == (w, h), icon
        assert img.mode == "RGB", f"{icon['href']} has an alpha channel; iOS paints transparency black"
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            assert max(img.getpixel(corner)) < 48, f"{icon['href']}: corners must be filled with the dark background (iOS rounds them itself)"


def test_every_launch_image_matches_its_media_query_and_none_is_orphaned():
    splash = links("apple-touch-startup-image")
    assert len(splash) >= 15
    referenced = set()
    for tag in splash:
        m = re.search(r"device-width: (\d+)px\) and \(device-height: (\d+)px\) and \(-webkit-device-pixel-ratio: (\d)\)", tag["media"])
        assert m and "portrait" in tag["media"], tag
        w, h, dpr = (int(v) for v in m.groups())
        img = png(tag["href"])
        assert img.size == (w * dpr, h * dpr), f"{tag['href']} is {img.size}, the media query expects {(w * dpr, h * dpr)}"
        assert img.mode == "RGB"
        referenced.add(Path(tag["href"]).name)
    on_disk = {p.name for p in (FRONT / "splash").glob("*.png")}
    assert on_disk == referenced, f"orphaned or missing launch images: {on_disk ^ referenced}"


def test_manifest_is_installable():
    manifest = json.loads((FRONT / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/" and manifest["id"] == "/"
    purposes = {(i["sizes"], i.get("purpose", "any")) for i in manifest["icons"]}
    assert ("192x192", "any") in purposes and ("512x512", "any") in purposes and ("512x512", "maskable") in purposes
    for icon in manifest["icons"]:
        assert icon["type"] == "image/png", icon          # an SVG ("any") entry can be picked by iOS and gives a blank icon
        w, h = (int(v) for v in icon["sizes"].split("x"))
        assert png(icon["src"]).size == (w, h), icon


def test_the_native_behaviour_script_is_cached_for_offline_use():
    sw = (FRONT / "sw.js").read_text(encoding="utf-8")
    for needed in ("/js/pwa.js", "/js/main.js"):
        assert needed in sw


def test_the_page_declares_one_png_favicon_and_one_touch_icon_and_no_svg_icon():
    icon = links("icon")
    assert len(icon) == 1 and icon[0]["type"] == "image/png" and png(icon[0]["href"]).size == (32, 32)
    assert not [i for i in links("icon") + links("apple-touch-icon") if i["href"].endswith(".svg")]


def test_the_default_places_iOS_and_browsers_look_serve_real_images_and_missing_files_are_404(real):
    for path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/icons/apple-touch-icon.png"):
        res = real.get(path)
        assert res.status_code == 200 and res.headers["Content-Type"] == "image/png" and res.data[:8] == b"\x89PNG\r\n\x1a\n", path
    assert real.get("/favicon.ico").headers["Content-Type"] == "image/png"
    assert real.get("/icons/nope.png").status_code == 404 and real.get("/apple-touch-icon-120x120.png").status_code == 404
    assert real.get("/some/screen").headers["Content-Type"].startswith("text/html")          # app routes still get the app
