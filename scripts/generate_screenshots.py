#!/usr/bin/env python3
"""Regenerate the README screenshots in docs/assets from a throwaway demo instance.

    pip install -r backend/requirements.txt playwright pillow
    python scripts/generate_screenshots.py           # CHROMIUM_PATH=/path/to/chrome if needed

The script starts its own app (the Flask app from backend/, serving frontend/) on a free local port against
a scratch SQLite database, fills it with the Dutch demo data below through the real API (so every
validator runs), drives Chromium through the screens and wraps each screenshot in a device frame: a browser
window for the desktop, an iPhone (installed app: dark status strip, dynamic island) and an Android phone
(accent-coloured status bar, punch-hole camera). Nothing touches a real installation.

The database is a SQLite file in the script's scratch folder, removed afterwards.

The screenshots are the only output: docs/assets/{desktop,ios,android}-*.png, which README.md and
README.nl.md show. Change what the screens look like and re-run this; do not edit the PNGs by hand.
"""
import argparse
import base64
import io
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import jwt
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
sys.path.insert(0, str(ROOT / "backend"))

SECRET = "screenshots-" + "x" * 40
ACCENT = "#6c5ce7"                       # the default accent: the Android status bar takes the theme colour

IOS = {"w": 393, "h": 852, "safe": {"top": "59px", "bottom": "34px"},
       "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"}
ANDROID = {"w": 412, "h": 887, "safe": {},
           "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"}
STATUS_BAR = 28                          # height of the Android status bar, drawn by the frame (the page sits below it)
DESKTOP = {"w": 1280, "h": 860}


# --- database and app ---------------------------------------------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_app(database_path, upload_dir, port):
    from app import create_app
    from app.config import Config
    from app.db import run_migrations

    run_migrations(database_path)
    os.environ["APP_COMMIT"] = "dev"                  # the sidebar shows vX.Y.Z (dev): the same every run, so images only change when the UI does
    os.environ["PUSH_WORKER"] = "off"
    origin = f"http://localhost:{port}"
    cfg = Config(database_path=database_path, session_secret=SECRET, setup_code="demo", rp_id="localhost", rp_name="3D Print Pricing",
                 rp_origins=(origin,), session_hours=24, cookie_secure=False, static_dir=str(ROOT / "frontend"),
                 upload_dir=upload_dir, max_upload_mb=5)
    app = create_app(cfg)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return app, origin, server


# --- demo data ------------------------------------------------------------------------------------------------------

class Api:
    """The API through Flask's test client, signed in as the demo user."""

    def __init__(self, app, origin, user_id):
        self.client, self.origin = app.test_client(), origin
        now = datetime.now(timezone.utc)
        self.token = jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=24)}, SECRET, algorithm="HS256")
        self.client.set_cookie("pp_session", self.token)

    def __call__(self, method, path, body=None):
        res = self.client.open(path, method=method, json=body, headers={"Origin": self.origin})
        if res.status_code >= 400:
            sys.exit(f"{method} {path} -> {res.status_code} {res.get_data(as_text=True)}")
        return res.get_json()


def seed_library(api):
    """The filament library, filled the way a user would: through the JSON import (the same validators as typing it in)."""
    def entry(brand, kind, material, colour, hexc, filament_id, barcode, price, nozzle, bed, refill=False, weight=1000.0):
        return {"brand": brand, "product_type": kind, "material": material, "colour": colour, "colour_hex": hexc, "filament_id": filament_id,
                "sku": "", "barcode": barcode, "refill": refill, "roll_weight_g": weight, "diameter_mm": 1.75, "print_temp_c": nozzle,
                "bed_temp_c": bed, "price": price, "notes": ""}

    filaments = [
        entry("Bambu Lab", "Basic", "PLA", "Zwart", "#1c1c1e", "10101", "6975337030011", 19.99, 220, 55),
        entry("Bambu Lab", "Basic", "PLA", "Wit", "#f2f2f2", "10100", "6975337030028", 19.99, 220, 55, refill=True),
        entry("Bambu Lab", "Basic", "PLA", "Blauw", "#2e6fdb", "10600", "6975337030042", 19.99, 220, 55),
        entry("Bambu Lab", "Matte", "PLA", "Charcoal Rood", "#c0392b", "11200", "6975337030035", 22.49, 220, 55),
        entry("Bambu Lab", "Silk", "PLA", "Goud", "#d4a017", "13400", "6975337030059", 26.99, 230, 55),
        entry("Bambu Lab", "95A HF", "TPU", "Geel", "#f1c40f", "53400", "6975337030066", 34.99, 230, 35, weight=500.0),
        entry("Sunlu", "HS", "PETG", "Transparant", "#cfe8f3", "", "6970000112233", 17.50, 245, 75),
        entry("Polymaker", "PolyTerra", "PLA", "Salie", "#7fa37a", "", "6970000445566", 21.95, 210, 55),
    ]
    api("POST", "/api/filament-library/import", {"format": "printpricing-filament-library", "format_version": 1, "filaments": filaments})


def seed(api):
    tariff = api("POST", "/api/tariffs", {"name": "Thuis (vast tarief)", "price_per_kwh": "0.28", "is_default": True})
    api("POST", "/api/tariffs", {"name": "Dalurentarief", "price_per_kwh": "0.21", "is_default": False})

    def printer(name, price, hours, kw):
        return api("POST", "/api/printers", {"name": name, "purchase_price": price, "lifetime_hours": hours, "power_kw": kw, "notes": "", "archived": False})

    printers = {"p1s": printer("Bambu Lab P1S", "699", "5000", "0.11"), "a1": printer("Bambu Lab A1 mini", "249", "3500", "0.08"),
                "x1": printer("Bambu Lab X1 Carbon", "1299", "8000", "0.14")}

    def box(name, price):
        return api("POST", "/api/packaging", {"name": name, "price": price, "notes": "", "archived": False})

    pack = {"s": box("Verzenddoos S (15×10×5 cm)", "0.42"), "m": box("Verzenddoos M (25×18×10 cm)", "0.68"),
            "f": box("Bubbeltjesfolie (per meter)", "0.35"), "w": box("Pakbon + bedankkaartje", "0.12")}

    def catalogue(path, name, price, unit="stuks"):
        return api("POST", path, {"name": name, "price": price, "unit": unit, "notes": "", "archived": False})

    extra = {"schroef": catalogue("/api/parts", "M2.5 schroeven", "0.06"), "jst": catalogue("/api/parts", "JST-connector 2-pins", "0.12"),
             "draad": catalogue("/api/parts", "Dupont-kabeltjes", "0.85", "m"),
             "kabel": catalogue("/api/accessories", "USB-C kabel", "1.40"), "lader": catalogue("/api/accessories", "USB-lader 5 V / 3 A", "4.95")}

    def roll(brand, kind, material, colour, hexc, price, left, barcode, nozzle, bed, notify=False, weight="1000"):
        return api("POST", "/api/spools", {"brand": brand, "product_type": kind, "material": material, "colour": colour, "colour_hex": hexc,
                                           "roll_weight_g": weight, "price": price, "remaining_g": left, "barcode": barcode, "diameter_mm": "1.75",
                                           "print_temp_c": nozzle, "bed_temp_c": bed, "notes": "", "notify_low": notify, "archived": False})

    sp = {
        "zwart": roll("Bambu Lab", "Basic", "PLA", "Zwart", "#1c1c1e", "19.99", "720", "6975337030011", 220, 55, True),
        "zwart2": roll("Bambu Lab", "Basic", "PLA", "Zwart", "#1c1c1e", "19.99", "1000", "6975337030011", 220, 55, True),
        "wit": roll("Bambu Lab", "Basic", "PLA", "Wit", "#f2f2f2", "19.99", "410", "6975337030028", 220, 55),
        "rood": roll("Bambu Lab", "Matte", "PLA", "Charcoal Rood", "#c0392b", "22.49", "865", "6975337030035", 220, 55),
        "blauw": roll("Bambu Lab", "Basic", "PLA", "Blauw", "#2e6fdb", "19.99", "255", "6975337030042", 220, 55, True),
        "goud": roll("Bambu Lab", "Silk", "PLA", "Goud", "#d4a017", "26.99", "930", "6975337030059", 230, 55),
        "petg": roll("Sunlu", "HS", "PETG", "Transparant", "#cfe8f3", "17.50", "1000", "6970000112233", 245, 75),
        "tpu": roll("Bambu Lab", "95A HF", "TPU", "Geel", "#f1c40f", "34.99", "310", "6975337030066", 230, 35, weight="500"),
        "groen": roll("Polymaker", "PolyTerra", "PLA", "Salie", "#7fa37a", "21.95", "580", "6970000445566", 210, 55),
    }

    def fil(key, label, grams):
        s = sp[key]
        return {"spool_id": s["id"], "label": label, "grams": str(grams),
                "price_per_kg": str(round(float(s["price"]) / float(s["roll_weight_g"]) * 1000, 2))}

    def dep(key, hours):
        p = printers[key]
        return {"label": f"Afschrijving {p['name']}", "printer_id": p["id"], "hours": str(hours),
                "price_per_hour": str(round(float(p["purchase_price"]) / float(p["lifetime_hours"]), 4))}

    def energy(key, hours):
        p = printers[key]
        return {"label": f"Stroom {p['name']}", "tariff_id": tariff["id"], "hours": str(hours), "kw": p["power_kw"], "price_per_kwh": tariff["price_per_kwh"]}

    def part(group, label, qty, unit, price, packaging=None, **link):
        return {"group": group, "packaging_id": packaging["id"] if packaging else "", "label": label, "quantity": str(qty), "unit": unit, "unit_price": str(price), **link}

    def calc(name, fils, hours, printer_key, parts, margin="120", url=""):
        return api("POST", "/api/projects", {
            "name": name, "notes": "", "margin_pct": margin, "vat_pct": "21", "source_url": url,
            "data": {"filament": fils, "parts": parts, "print": {"depreciation": [dep(printer_key, hours)], "energy": [energy(printer_key, hours)]}}})

    calc("Telefoonstandaard Hexa", [fil("zwart", "PLA Basic Zwart", 38)], 2.4, "p1s", [], url="https://makerworld.com/nl/models/123456")
    calc("Bloempot Gyroïde (medium)", [fil("groen", "PolyTerra Salie", 112)], 5.2, "p1s", [], margin="150")
    calc("Kabelhouder bureau (set van 4)", [fil("wit", "PLA Basic Wit", 46)], 3.1, "a1", [], margin="140")
    calc("Sleutelhanger Vos", [fil("rood", "PLA Matte Rood", 9), fil("wit", "PLA Basic Wit", 3)], 0.9, "a1",
         [part("onderdeel", "Sleutelring", 1, "stuks", "0.15")], margin="250")
    calc("Vaas Silk Goud", [fil("goud", "PLA Silk Goud", 164)], 7.8, "x1", [], margin="130")
    # The one the screenshots open: several lines per section, and a model link so the file box is filled in.
    calc("Raspberry Pi 5 behuizing", [fil("zwart", "PLA Basic Zwart", 58), fil("blauw", "PLA Basic Blauw", 6)], 4.4, "p1s",
         [part("onderdeel", "M2.5 schroeven", 4, "stuks", "0.06", part_id=extra["schroef"]["id"]),
          part("oplader", "USB-C kabel", 1, "stuks", "1.40", accessory_id=extra["kabel"]["id"])],
         margin="110", url="https://makerworld.com/nl/models/987654")
    calc("Fietsbel-houder (TPU)", [fil("tpu", "TPU 95A Geel", 21)], 1.6, "a1", [], margin="200")

    seed_library(api)

    projects = {p["name"]: p for p in api("GET", "/api/projects")}
    people = [
        ("Studio Bloem", "Keizersgracht 214", "1016 EV", "Amsterdam", "info@studiobloem.example", "020 555 0142", "Vaste afnemer."),
        ("Fam. Janssen", "Dorpsstraat 18", "3512 AB", "Utrecht", "m.janssen@example.nl", "06 1234 5678", ""),
        ("De Vries Installatie", "Industrieweg 7", "5642 HZ", "Eindhoven", "inkoop@devries-installatie.example", "040 555 0199", ""),
        ("Lotte Smit", "Molenlaan 3", "2011 KC", "Haarlem", "lotte@example.nl", "06 8765 4321", ""),
        ("Café 't Hoekje", "Marktplein 1", "6811 CG", "Arnhem", "bestel@hoekje.example", "026 555 0123", "Menukaarthouders."),
    ]
    customers = {name: api("POST", "/api/customers", {"number": "", "name": name, "address": addr, "postal_code": zip_, "city": city,
                                                      "country": "Nederland", "email": mail, "phone": phone, "notes": note})
                 for name, addr, zip_, city, mail, phone, note in people}

    def day(offset):
        return (date.today() + timedelta(days=offset)).isoformat()

    def line(name, qty, description=None, margin=None):
        """A model on an order: the calculation's cost price with its margin (or this order's own); the server works out the price."""
        project = api("GET", f"/api/projects/{projects[name]['id']}")
        return {"project_id": project["id"], "description": description or name, "quantity": qty, "vat_pct": "21",
                "cost_price": project["totals"]["cost_price"], "margin_pct": project["margin_pct"] if margin is None else margin}

    def packaging(key, qty=1):
        """Packaging material on an order: a normal line at cost price (margin 0)."""
        return {"project_id": None, "description": pack[key]["name"], "quantity": qty, "vat_pct": "21",
                "cost_price": pack[key]["price"], "margin_pct": "0"}

    # Margin per line and rounding per order: a regular customer gets a lower margin, a café a price ending in ,95.
    orders = [
        ("Studio Bloem", "nieuw", -1, 6, "Plantenbakken voor de winkel", "x.95", [line("Bloempot Gyroïde (medium)", 12, margin="110"), line("Vaas Silk Goud", 4), packaging("m", 2), packaging("f", 3), packaging("w")]),
        ("Fam. Janssen", "verwerkt", -3, 3, "Telefoonstandaards", "0.50", [line("Telefoonstandaard Hexa", 3), packaging("s"), packaging("w")]),
        ("Café 't Hoekje", "verstuurd", -6, -1, "Menukaarthouders", "x.95", [line("Kabelhouder bureau (set van 4)", 6, "Menukaarthouder (set van 4)")]),
        ("De Vries Installatie", "afgehandeld", -14, -8, "Behuizingen Raspberry Pi 5", "1.00", [line("Raspberry Pi 5 behuizing", 20, margin="90")]),
        ("Lotte Smit", "afgehandeld", -20, -15, "Sleutelhangers", "x.99", [line("Sleutelhanger Vos", 8), line("Fietsbel-houder (TPU)", 2)]),
        ("Studio Bloem", "afgehandeld", -30, -24, "Vazen", "x.95", [line("Vaas Silk Goud", 6, margin="110")]),
    ]
    for name, status, ordered, delivered, subject, rounding, lines in orders:
        api("POST", "/api/orders", {"customer_id": customers[name]["id"], "status": status, "order_date": day(ordered), "delivery_date": day(delivered),
                                    "subject": subject, "notes": "", "price_rounding": rounding, "lines": lines})
    return projects["Raspberry Pi 5 behuizing"]["id"]


# --- capture --------------------------------------------------------------------------------------------------------

def open_context(browser, origin, token, *, width, height, scale, device=None):
    """A browser context for one screen size. For a phone: touch, the device's user agent, a faked safe area (the
    CSS reads env(safe-area-inset-*), which Chromium on a desktop does not have) and, on the iPhone, the installed-app mode."""
    phone = device is not None
    ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale, is_mobile=phone, has_touch=phone,
                              user_agent=device["ua"] if phone else None, service_workers="block", locale="nl-NL",
                              timezone_id="Europe/Amsterdam", bypass_csp=True)
    ctx.add_cookies([{"name": "pp_session", "value": token, "url": origin}])
    if device is IOS:
        ctx.add_init_script("Object.defineProperty(navigator, 'standalone', { value: true })")     # what makes the app "installed"
    safe = device["safe"] if phone else {}

    def css(route):
        res = route.fetch()
        body = res.text()
        for side in ("top", "right", "bottom", "left"):
            body = body.replace(f"env(safe-area-inset-{side})", safe.get(side, "0px"))
        route.fulfill(response=res, body=body)

    ctx.route("**/css/app.css*", css)
    return ctx


def settle(page):
    page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(900)


def scroll_to_heading(page, text, offset):
    page.evaluate("""([text, offset]) => { const h = [...document.querySelectorAll('h2')].find((e) => e.textContent.trim() === text);
                     if (h) window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - offset); }""", [text, offset])
    page.wait_for_timeout(400)


def dismiss_banners(page):
    for name in ("Begrepen", "Niet nu"):
        button = page.get_by_role("button", name=name)
        if button.count():
            button.first.click()


def new_roll_form(page):
    """The 'Nieuwe rol' form, open on the library pick-list at its top."""
    page.get_by_role("button", name="Nieuwe rol").first.click()
    page.wait_for_function("document.querySelector('#f-library')?.options.length > 1")
    page.wait_for_timeout(400)


def capture(browser, api, origin, project_id, raw):
    def prefs(**p):
        api("PUT", "/api/preferences", {"language": "nl", "business_mode": True, "navbar_glass": 55, "accent": ACCENT, **p})

    routes = {"list": "berekeningen", "editor": f"berekeningen/{project_id}", "orders": "bestellingen", "filament": "filament",
              "library": "instellingen/filamenten", "settings": "instellingen/weergave", "newroll": "filament"}

    # Desktop: the editor in light and dark, the rest in light.
    for theme in ("light", "dark"):
        prefs(theme=theme, navbar_style="ios")
        ctx = open_context(browser, origin, api.token, width=DESKTOP["w"], height=DESKTOP["h"], scale=1.5)
        page = ctx.new_page()
        for name in ("editor", "list", "filament", "orders", "library", "settings", "newroll") if theme == "light" else ("editor",):
            page.goto(f"{origin}/#/{routes[name]}")
            settle(page)
            if name == "newroll":
                new_roll_form(page)
            page.screenshot(path=str(raw / f"desktop-{name}-{theme}.png"))
        ctx.close()

    # The accent colour recolours the whole interface: Settings -> Display in dark, in teal.
    prefs(theme="dark", navbar_style="ios", accent="#0c9aa6")
    ctx = open_context(browser, origin, api.token, width=DESKTOP["w"], height=DESKTOP["h"], scale=1.5)
    page = ctx.new_page()
    page.goto(f"{origin}/#/{routes['settings']}")
    settle(page)
    page.screenshot(path=str(raw / "desktop-settings-dark.png"))
    ctx.close()

    # Phones, in light: the navigation bar style is the point, so each platform gets its own.
    for kind, device in (("ios", IOS), ("android", ANDROID)):
        prefs(theme="light", navbar_style=kind)
        ctx = open_context(browser, origin, api.token, width=device["w"], height=device["h"], scale=2, device=device)
        page = ctx.new_page()
        for name, route in routes.items():
            page.goto(f"{origin}/#/{route}")
            settle(page)
            dismiss_banners(page)
            if name == "editor":
                scroll_to_heading(page, "Kostprijs", 150 if kind == "ios" else 90)
            elif name == "newroll":
                new_roll_form(page)
            elif kind == "ios":
                # As you would use it: the sticky title bar has to clear the status strip, which only shows once the page has scrolled.
                page.evaluate("window.scrollTo(0, 64)")
                page.wait_for_timeout(300)
            page.screenshot(path=str(raw / f"{kind}-{name}-light.png"))
        ctx.close()
    prefs(theme="light", navbar_style="ios")


# --- device frames --------------------------------------------------------------------------------------------------

def status_icons(color):
    return f"""
  <svg width="18" height="12" viewBox="0 0 18 12" fill="{color}"><rect x="0" y="8" width="3" height="4" rx="1"/><rect x="5" y="5" width="3" height="7" rx="1"/><rect x="10" y="2.5" width="3" height="9.5" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1"/></svg>
  <svg width="17" height="12" viewBox="0 0 17 12" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round"><path d="M1.5 4.2a10 10 0 0 1 14 0"/><path d="M4 7a6.4 6.4 0 0 1 9 0"/><circle cx="8.5" cy="10" r="1" fill="{color}" stroke="none"/></svg>
  <svg width="27" height="13" viewBox="0 0 27 13" fill="none"><rect x=".5" y=".5" width="23" height="12" rx="3.5" stroke="{color}" opacity=".5"/><rect x="2" y="2" width="20" height="9" rx="2.2" fill="{color}"/><path d="M25 4.5v4" stroke="{color}" stroke-width="1.6" stroke-linecap="round" opacity=".5"/></svg>"""


FRAME_CSS = f"""
 html,body{{margin:0;background:transparent}} body{{display:inline-block}}
 .phone{{background:#0d0d12;border-radius:62px;padding:12px;box-sizing:border-box;box-shadow:inset 0 0 0 2px #3a3a44;position:relative}}
 .phone.android{{border-radius:48px}}
 .screen{{position:relative;overflow:hidden;background:#fff}} .screen img{{display:block}}
 .astatus{{position:absolute;left:0;right:0;top:0;height:{STATUS_BAR}px;background:{ACCENT}}}
 .sb{{position:absolute;left:0;right:0;top:0;display:flex;justify-content:space-between;align-items:center;color:#fff;font:600 16px/1 -apple-system,'Inter','Helvetica Neue',Arial,sans-serif}}
 .sb.ios{{height:59px;padding:6px 34px 0 48px;box-sizing:border-box}}
 .sb.android{{height:{STATUS_BAR}px;padding:0 20px;font-size:13px;font-weight:500}}
 .sb .icons{{display:flex;gap:6px;align-items:center}}
 .island{{position:absolute;top:11px;left:50%;transform:translateX(-50%);width:122px;height:35px;border-radius:20px;background:#000}}
 .punch{{position:absolute;top:7px;left:50%;transform:translateX(-50%);width:14px;height:14px;border-radius:50%;background:#000;box-shadow:0 0 0 2px #1b1b22}}
 .home{{position:absolute;left:50%;transform:translateX(-50%);border-radius:3px;opacity:.9}}
 .home.ios{{bottom:8px;width:136px;height:5px;background:#111}} .home.android{{bottom:7px;width:108px;height:4px;background:#fff}}
 .win{{width:{DESKTOP['w']}px;border-radius:12px;overflow:hidden;background:#fff;box-shadow:0 0 0 1px rgba(128,128,150,.35)}}
 .win .bar{{height:40px;display:flex;align-items:center;gap:8px;padding:0 14px;background:#ececf2;font:13px -apple-system,'Inter',Arial,sans-serif;color:#555}}
 .win.dark .bar{{background:#23222e;color:#aaa}}
 .win .dot{{width:12px;height:12px;border-radius:50%}}
 .win .url{{margin:0 auto;transform:translateX(-30px);width:360px;height:26px;border-radius:8px;background:#fff;display:flex;align-items:center;justify-content:center}}
 .win.dark .url{{background:#14131c}}
 .win img{{display:block;width:{DESKTOP['w']}px;height:{DESKTOP['h']}px}}"""


def data_uri(path):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def phone_html(kind, png):
    ios, device = kind == "ios", IOS if kind == "ios" else ANDROID
    w, h = device["w"], device["h"] + (0 if ios else STATUS_BAR)
    image = (f'<img src="{png}" style="width:{w}px;height:{h}px">' if ios else
             f'<img src="{png}" style="position:absolute;top:{STATUS_BAR}px;left:0;width:{w}px;height:{device["h"]}px">')
    return (f'<div class="phone {kind}" style="width:{w + 24}px;height:{h + 24}px"><div class="screen" style="width:{w}px;height:{h}px;border-radius:{46 if ios else 34}px">'
            f'{"" if ios else "<div class=astatus></div>"}{image}'
            f'<div class="sb {kind}">{"<b>9:41</b>" if ios else "<span>12:30</span>"}<span class="icons">{status_icons("#fff")}</span></div>'
            f'{"<div class=island></div>" if ios else "<div class=punch></div>"}<div class="home {kind}"></div></div></div>')


def window_html(png, theme):
    return (f'<div class="win {theme}"><div class="bar"><i class="dot" style="background:#ff5f57"></i><i class="dot" style="background:#febc2e"></i>'
            f'<i class="dot" style="background:#28c840"></i><div class="url">print.voorbeeld.nl</div></div><img src="{png}"></div>')


def frame(browser, html, selector, out):
    ctx = browser.new_context(device_scale_factor=1.5, viewport={"width": 1400, "height": 1000})
    page = ctx.new_page()
    page.set_content(f"<!doctype html><meta charset=utf-8><style>{FRAME_CSS}</style>{html}")
    page.evaluate("Promise.all([...document.images].map((i) => i.decode()))")
    shot = page.locator(selector).first.screenshot(omit_background=True)
    ctx.close()
    Image.open(io.BytesIO(shot)).save(out, optimize=True)


def frames(browser, raw):
    OUT.mkdir(parents=True, exist_ok=True)
    names = {"list": "calculations", "editor": "calculation", "orders": "orders", "filament": "filament", "library": "library", "newroll": "new-roll", "settings": "settings"}
    for kind in ("ios", "android"):
        for key, name in names.items():
            frame(browser, phone_html(kind, data_uri(raw / f"{kind}-{key}-light.png")), ".phone", OUT / f"{kind}-{name}.png")
    for key, name in names.items():
        frame(browser, window_html(data_uri(raw / f"desktop-{key}-light.png"), "light"), ".win", OUT / f"desktop-{name}.png")
    frame(browser, window_html(data_uri(raw / "desktop-editor-dark.png"), "dark"), ".win", OUT / "desktop-calculation-dark.png")
    frame(browser, window_html(data_uri(raw / "desktop-settings-dark.png"), "dark"), ".win", OUT / "desktop-settings-dark.png")


# --- main -----------------------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="pp-shots-"))
    server = app = None
    try:
        port = free_port()
        app, origin, server = start_app(str(work / "demo.sqlite3"), str(work / "uploads"), port)
        with app.extensions["pool"].connection() as conn:
            user_id = conn.execute("INSERT INTO users (display_name, role, is_owner) VALUES ('Demo', 'admin', true) RETURNING id").fetchone()["id"]
        api = Api(app, origin, user_id)
        project_id = seed(api)

        raw = work / "raw"
        raw.mkdir()
        with sync_playwright() as p:
            kwargs = {"executable_path": os.environ["CHROMIUM_PATH"]} if os.environ.get("CHROMIUM_PATH") else {}
            browser = p.chromium.launch(**kwargs)
            capture(browser, api, origin, project_id, raw)
            frames(browser, raw)
            browser.close()
        print(f"Wrote {len(list(OUT.glob('*.png')))} images to {OUT.relative_to(ROOT)}")
    finally:
        if server:
            server.shutdown()
        if app:
            app.extensions["pool"].close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
