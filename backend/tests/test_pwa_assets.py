"""The installed-app surface: iOS icons, launch images, manifest and the no-zoom viewport.

These are static files, so the failure mode is drift: a launch image that no <link> points at, a link
whose media query does not match the PNG's pixel size, or an icon iOS would paint with a black corner.
"""
import json
import re
from pathlib import Path

from PIL import Image

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
    sizes = {i.get("sizes", "180x180") for i in icons}
    assert {"180x180", "167x167", "152x152", "120x120"} <= sizes
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
        if icon["type"] == "image/png":
            w, h = (int(v) for v in icon["sizes"].split("x"))
            assert png(icon["src"]).size == (w, h), icon


def test_the_native_behaviour_script_is_cached_for_offline_use():
    sw = (FRONT / "sw.js").read_text(encoding="utf-8")
    for needed in ("/js/pwa.js", "/js/main.js"):
        assert needed in sw
