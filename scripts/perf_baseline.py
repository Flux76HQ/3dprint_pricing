#!/usr/bin/env python3
"""Measure the paths the performance work is judged by, on a throwaway database of a stated size.

    python scripts/perf_baseline.py                       # prints the tables of docs/performance.md
    python scripts/perf_baseline.py --json numbers.json   # and keeps the raw numbers

It follows App-Guidance's performance playbook: a number first, with a date and a data size, before and after every change.
The data is the demo data of `scripts/generate_screenshots.py` (the same `seed`), copied until it has the size asked for, plus
product images written straight into `project_images` (making real ones needs OpenAI). The server is Gunicorn started with the
flags of `deploy/entrypoint.sh`, read from that file, so what is measured is what ships; only the port, the access log and
the workers that would write in the background (push, automatic backup) differ.

What is measured:

* the API, over one kept-alive connection: `GET /api/projects` on a server that has just started and after that;
* the browser (Chromium through Playwright, service worker allowed): opening the app on the model list with an empty cache and
  again with a filled one, and opening the model editor. Requests and bytes are counted in Gunicorn's access log, so a request
  made by the service worker counts like one made by the page;
* the server under load: several clients at once, and a small read while long requests run (backups being downloaded, which
  compute all the time, and uploads that arrive slowly, which mostly wait).

It needs what `generate_screenshots.py` needs (`playwright`, `pillow`; `CHROMIUM_PATH` if the browser is elsewhere) and the
packages of `backend/requirements.txt`. It never touches a real installation. Timings are those of the machine it runs on:
compare a before and an after from the same machine, never against the numbers of another one.
"""
import argparse
import http.client
import io
import json
import os
import platform
import random
import re
import shlex
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

SECRET = "perf-baseline-" + "x" * 40
COMMIT = "c0ffee1"                      # a release build: `dev` is the one build whose files are never kept by a browser
LOG_FORMAT = "%(s)s %(B)s %(D)s %(m)s %(U)s"          # status, bytes of the body, microseconds, method, path
BROWSER_CONNECTIONS = 6                 # what a browser opens to one host over HTTP/1.1


# --- data -------------------------------------------------------------------------------------------------------------

def photo(seed: int, edge: int) -> bytes:
    """A JPEG that is about as large as a real product photo of this size: soft shapes with grain on top (a flat colour would be
    a tenth of the size and flatter the numbers)."""
    from PIL import Image, ImageFilter
    rnd = random.Random(seed)
    small = Image.frombytes("RGB", (24, 24), bytes(rnd.getrandbits(8) for _ in range(24 * 24 * 3)))
    image = small.resize((edge, edge), Image.BICUBIC)
    grain = Image.effect_noise((edge, edge), 22).convert("RGB")
    image = Image.blend(image, grain, 0.18).filter(ImageFilter.SMOOTH)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


def build(database_path: str, upload_dir: str, size: dict) -> dict:
    """The demo data, grown to `size`, written through the API so every total is the calculator's own."""
    import generate_screenshots as demo
    from app import create_app
    from app.config import Config
    from app.db import run_migrations

    run_migrations(database_path)
    os.environ.update(PUSH_WORKER="off", AUTO_BACKUP_WORKER="off", APP_COMMIT=COMMIT)
    cfg = Config(database_path=database_path, session_secret=SECRET, setup_code="perf", rp_id="localhost", rp_name="3D Print Pricing",
                 rp_origins=("http://localhost",), session_hours=24, cookie_secure=False, static_dir=str(ROOT / "frontend"),
                 upload_dir=upload_dir, max_upload_mb=5, ai_images_enabled=True, update_check=False)
    app = create_app(cfg)
    with app.extensions["pool"].connection() as conn:
        user_id = conn.execute("INSERT INTO users (display_name, role, is_owner) VALUES ('Demo', 'admin', true) RETURNING id").fetchone()["id"]
    demo.SECRET = SECRET
    api = demo.Api(app, "http://localhost", user_id)
    demo.seed(api)
    rnd = random.Random(76)

    models = [api("GET", f"/api/projects/{p['id']}") for p in api("GET", "/api/projects")]
    for n in range(len(models), size["models"]):
        src = models[n % 7]
        models.append(api("POST", "/api/projects", {"name": f"{src['name']} (variant {n})", "notes": src["notes"], "margin_pct": src["margin_pct"],
                                                    "vat_pct": src["vat_pct"], "source_url": src["source_url"], "data": src["data"]}))
    rolls = api("GET", "/api/spools")
    for n in range(len(rolls), size["rolls"]):
        src = rolls[n % 9]
        api("POST", "/api/spools", {key: src[key] for key in ("brand", "product_type", "material", "colour_hex", "roll_weight_g", "price", "barcode",
                                                               "diameter_mm", "print_temp_c", "bed_temp_c", "notes", "notify_low", "archived")}
            | {"colour": f"{src['colour']} {n // 9}", "remaining_g": str(rnd.randrange(50, 1000))})
    customers = api("GET", "/api/customers")
    for n in range(len(customers), size["customers"]):
        customers.append(api("POST", "/api/customers", {"number": "", "name": f"Klant {n}", "address": f"Straat {n}", "postal_code": "1234 AB",
                                                        "city": rnd.choice(["Utrecht", "Haarlem", "Arnhem", "Zwolle"]), "country": "Nederland",
                                                        "email": f"klant{n}@example.nl", "phone": "", "notes": ""}))
    statuses = ["nieuw", "verwerkt", "verstuurd", "afgehandeld", "afgehandeld", "afgehandeld"]
    for n in range(len(api("GET", "/api/orders")), size["orders"]):
        lines = [{"project_id": m["id"], "description": m["name"], "quantity": rnd.randrange(1, 12), "vat_pct": "21",
                  "cost_price": m["totals"]["cost_price"], "margin_pct": m["margin_pct"]} for m in rnd.sample(models, rnd.randrange(1, 5))]
        ordered = date.today() - timedelta(days=rnd.randrange(0, 720))
        api("POST", "/api/orders", {"customer_id": rnd.choice(customers)["id"], "status": rnd.choice(statuses), "order_date": ordered.isoformat(),
                                    "delivery_date": (ordered + timedelta(days=6)).isoformat(), "subject": f"Bestelling {n}", "notes": "",
                                    "price_rounding": rnd.choice(["none", "x.95", "0.50"]), "lines": lines})

    # Product images: a photo and a made picture that is the cover, as the AI images screen leaves them, for the model the editor is
    # opened on and for the newest ones (the top of the list, which is what a browser loads the covers of).
    pictures = [photo(n, size["image_edge"]) for n in range(6)]
    owners = [models[5], *models[len(models) - size["images"] + 1:]]
    raw = sqlite3.connect(database_path)
    with raw:
        for n, model in enumerate(owners):
            for kind, cover in (("source", 0), ("generated", 1)):
                raw.execute("INSERT INTO project_images (project_id, kind, variant, mime, content, width_px, height_px, is_cover) VALUES (?,?,?,?,?,?,?,?)",
                            (model["id"], kind, None if kind == "source" else "square", "image/jpeg", pictures[(n + cover) % 6],
                             size["image_edge"], size["image_edge"], cover))
    raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw.close()
    app.extensions["pool"].close()
    token = api.token
    return {"token": token, "model_id": models[5]["id"], "image_bytes": round(statistics.mean(len(p) for p in pictures)),
            "database_mb": round(Path(database_path).stat().st_size / 1e6, 1)}


# --- the server, as the container starts it ---------------------------------------------------------------------------

def gunicorn_flags(env: dict) -> list:
    """The flags after `exec gunicorn` in deploy/entrypoint.sh, with its `${NAME:-default}` filled in from `env`."""
    script = (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8").replace("\\\n", " ")
    line = next(line for line in script.splitlines() if line.strip().startswith("exec gunicorn"))
    filled = re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", lambda m: env.get(m.group(1), m.group(2) or ""), line)
    return shlex.split(filled)[2:]


class Server:
    def __init__(self, work: Path, database_path: str, upload_dir: str, port: int, extra_env: dict):
        self.port, self.log_path = port, work / f"access-{port}.log"
        env = {**os.environ, "DATABASE_PATH": database_path, "SESSION_SECRET": SECRET, "SETUP_CODE": "perf", "UPLOAD_DIR": upload_dir,
               "STATIC_DIR": str(ROOT / "frontend"), "WEB_PORT": str(port), "APP_COMMIT": COMMIT, "AI_IMAGES_ENABLED": "TRUE",
               "PUSH_WORKER": "off", "AUTO_BACKUP_WORKER": "off", "PRINTPRICING_UPDATE_CHECK": "false", "PYTHONPATH": str(ROOT / "backend"),
               **extra_env}
        for name in ("RP_ID", "RP_ORIGINS", "PROXY_HOPS"):
            env.pop(name, None)
        flags = gunicorn_flags(env)
        self.flags = " ".join(flags)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", *flags, "--access-logfile", str(self.log_path),
             "--access-logformat", LOG_FORMAT, "--log-level", "warning"], cwd=ROOT / "backend", env=env)
        deadline = time.monotonic() + 30
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", "/healthz")
                if conn.getresponse().status == 200:
                    break
            except OSError:
                if time.monotonic() > deadline or self.process.poll() is not None:
                    raise SystemExit("Gunicorn did not start.") from None
                time.sleep(0.1)
        self.mark()

    def mark(self) -> None:
        time.sleep(0.25)                                  # the line of a request is written just after its answer
        self.offset = self.log_path.stat().st_size

    def since_mark(self) -> list:
        """(status, bytes, milliseconds, method, path) of every request since `mark()`, without the health checks."""
        time.sleep(0.25)
        with self.log_path.open() as handle:
            handle.seek(self.offset)
            rows = [line.split(" ", 4) for line in handle.read().splitlines()]
        return [(int(s), int(b), int(d) / 1000, m, p) for s, b, d, m, p in rows if p != "/healthz"]

    def stop(self) -> None:
        self.process.terminate()
        self.process.wait(10)


class Client:
    """One kept-alive connection with the session cookie, as one of a browser's connections."""

    def __init__(self, port: int, token: str):
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        self.headers = {"Cookie": f"pp_session={token}", "Accept-Encoding": "gzip"}

    def get(self, path: str, headers: "dict | None" = None) -> "tuple[int, int, float, dict]":
        began = time.perf_counter()
        self.conn.request("GET", path, headers={**self.headers, **(headers or {})})
        res = self.conn.getresponse()
        body = res.read()
        return res.status, len(body), (time.perf_counter() - began) * 1000, dict(res.getheaders())


def spread(values: list) -> dict:
    ordered = sorted(values)
    return {"median_ms": round(statistics.median(ordered), 1), "p95_ms": round(ordered[max(0, round(len(ordered) * 0.95) - 1)], 1)}


def summary(rows: list) -> dict:
    """Requests that reached the server, by kind: the app's own files, the API, and the product images."""
    def kind(path):
        return "images" if path.startswith("/api/project-images/") else "api" if path.startswith("/api/") else "static"
    out = {"requests": len(rows), "bytes": sum(r[1] for r in rows), "server_ms": round(sum(r[2] for r in rows), 1)}
    for name in ("static", "api", "images"):
        mine = [r for r in rows if kind(r[4]) == name]
        out[name] = {"requests": len(mine), "not_modified": sum(1 for r in mine if r[0] == 304), "bytes": sum(r[1] for r in mine)}
    return out


# --- the measurements -------------------------------------------------------------------------------------------------

def measure_api(server: Server, token: str) -> dict:
    client = Client(server.port, token)
    status, size, first, headers = client.get("/api/projects")
    assert status == 200, status
    warm = [client.get("/api/projects")[2] for _ in range(40)]
    orders = [client.get("/api/orders")[2] for _ in range(20)]
    return {"projects": {"bytes": size, "encoding": headers.get("Content-Encoding", "none"), "first_ms": round(first, 1), **spread(warm)},
            "orders": {"bytes": client.get("/api/orders")[1], **spread(orders)}}


def measure_browser(server: Server, token: str, model_id: str) -> dict:
    from playwright.sync_api import sync_playwright
    origin = f"http://localhost:{server.port}"
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM_PATH"]} if os.environ.get("CHROMIUM_PATH") else {}))
        ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="nl-NL")
        ctx.add_cookies([{"name": "pp_session", "value": token, "url": origin}])

        def launch():
            page = ctx.new_page()
            server.mark()
            began = time.perf_counter()
            page.goto(f"{origin}/#/berekeningen")
            page.wait_for_selector("a.link-card")
            seen = (time.perf_counter() - began) * 1000
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)                  # the service worker fills its cache after the page is there
            return page, {"list_visible_ms": round(seen), **summary(server.since_mark())}

        page, out["launch_empty_cache"] = launch()
        page.close()
        page, _second = launch()                          # the first launch with a service worker in control; it settles here
        page.close()
        page, out["launch_filled_cache"] = launch()

        opened, rows = [], []
        for _ in range(5):
            page.goto(f"{origin}/#/berekeningen")
            page.wait_for_selector("a.link-card")
            page.wait_for_load_state("networkidle")
            server.mark()
            began = time.perf_counter()
            page.goto(f"{origin}/#/berekeningen/{model_id}")
            page.wait_for_selector(".editor")
            opened.append((time.perf_counter() - began) * 1000)
            page.wait_for_load_state("networkidle")
            rows = server.since_mark()
        out["open_editor"] = {"editor_visible_ms": round(statistics.median(opened)), **summary(rows)}
        out["editor_paths"] = [r[4] for r in rows if r[3] == "GET" and r[4].startswith("/api/") and not r[4].startswith("/api/project-images/")]
        browser.close()
    return out


def measure_editor_data(server: Server, token: str, paths: list) -> dict:
    """The GETs the editor sent, replayed the way a browser sends them: at once, over at most six connections."""
    clients = [Client(server.port, token) for _ in range(BROWSER_CONNECTIONS)]
    free, lock = list(clients), threading.Lock()

    def one(path):
        with lock:
            client = free.pop()
        try:
            return client.get(path)
        finally:
            with lock:
                free.append(client)

    walls, size = [], 0
    with ThreadPoolExecutor(BROWSER_CONNECTIONS) as pool:
        for _ in range(25):
            began = time.perf_counter()
            answers = list(pool.map(one, paths))
            walls.append((time.perf_counter() - began) * 1000)
            size = sum(a[1] for a in answers)
    return {"requests": len(paths), "bytes": size, **spread(walls)}


def measure_load(server: Server, token: str, clients: int = 8, seconds: float = 4.0) -> dict:
    stop = time.monotonic() + seconds
    took = []

    def run():
        client, mine = Client(server.port, token), []
        while time.monotonic() < stop:
            mine.append(client.get("/api/projects")[2])
        took.extend(mine)

    threads = [threading.Thread(target=run) for _ in range(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"clients": clients, "requests_per_second": round(len(took) / seconds, 1), **spread(took)}


def slow_upload(port: int, token: str, seconds: float) -> None:
    """A request whose body arrives slowly, as an upload over a poor connection does when no proxy in front collects it first."""
    body = json.dumps({"data": {}, "padding": "x" * 200_000}).encode()
    head = (f"POST /api/calculate HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nCookie: pp_session={token}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
    with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
        sock.sendall(head)
        step = len(body) // 20
        for n in range(20):
            sock.sendall(body[n * step:(n + 1) * step] if n < 19 else body[19 * step:])
            time.sleep(seconds / 20)
        while sock.recv(65536):
            pass


def measure_while_busy(server: Server, token: str, count: int, kind: str) -> dict:
    """How long a small read (`GET /api/printers`) takes while `count` long requests run. `backup`: a backup download, which reads every
    picture and is computing all the time. `upload`: a request that is mostly waiting, for its own body to arrive."""
    lengths, waits = [], []

    def long_request():
        began = time.perf_counter()
        if kind == "backup":
            Client(server.port, token).get("/api/backup")
        else:
            slow_upload(server.port, token, 1.5)
        lengths.append((time.perf_counter() - began) * 1000)

    for _ in range(3):
        threads = [threading.Thread(target=long_request) for _ in range(count)]
        for t in threads:
            t.start()
        time.sleep(0.05)                                 # the long requests are under way
        client = Client(server.port, token)
        while True:
            waits.append(client.get("/api/printers")[2])
            if not any(t.is_alive() for t in threads):
                break
            time.sleep(0.02)
        for t in threads:
            t.join()
    return {"kind": kind, "at_once": count, "long_ms": round(statistics.median(lengths)), "reads": len(waits),
            "median_ms": round(statistics.median(waits), 1), "slowest_ms": round(max(waits), 1)}


# --- the report -------------------------------------------------------------------------------------------------------

def kb(n: int) -> str:
    return f"{n / 1000:.0f} kB" if n >= 10_000 else f"{n / 1000:.1f} kB"


def report(r: dict) -> str:
    m, size = r["measured"], r["data"]
    lines = [f"Measured {r['date']} at commit `{r['commit']}` on {r['machine']}.",
             f"Data: {size['models']} models, {size['orders']} orders, {size['rolls']} rolls, {size['customers']} customers, {size['images'] * 2} product images "
             f"of about {kb(r['image_bytes'])} ({size['image_edge']} px); the database file is {r['database_mb']} MB.",
             f"Server: `gunicorn {r['gunicorn']}`.", "",
             "| What | Result |", "|---|---|"]
    a = m["api"]["projects"]
    lines += [f"| `GET /api/projects`, first request after a start | {a['first_ms']} ms, {kb(a['bytes'])} ({a['encoding']}) |",
              f"| `GET /api/projects`, after that | median {a['median_ms']} ms, p95 {a['p95_ms']} ms |",
              f"| `GET /api/orders` | median {m['api']['orders']['median_ms']} ms, p95 {m['api']['orders']['p95_ms']} ms, {kb(m['api']['orders']['bytes'])} |"]
    for key, label in (("launch_empty_cache", "Opening the app on the model list, empty browser cache"),
                       ("launch_filled_cache", "Opening it again, filled cache and a service worker")):
        b = m["browser"][key]
        lines.append(f"| {label} | list visible after {b['list_visible_ms']} ms; {b['requests']} requests reach the server, {kb(b['bytes'])}: "
                     f"{b['static']['requests']} files ({b['static']['not_modified']} answered 304, {kb(b['static']['bytes'])}), "
                     f"{b['api']['requests']} API ({kb(b['api']['bytes'])}), {b['images']['requests']} images ({kb(b['images']['bytes'])}) |")
    e, d = m["browser"]["open_editor"], m["editor_data"]
    lines += [f"| Opening the model editor from the list | visible after {e['editor_visible_ms']} ms; {e['api']['requests']} API requests, {kb(e['api']['bytes'])}, "
              f"{e['images']['requests']} images ({kb(e['images']['bytes'])}) |",
              f"| The editor's {d['requests']} GETs replayed over {BROWSER_CONNECTIONS} connections | median {d['median_ms']} ms, p95 {d['p95_ms']} ms, {kb(d['bytes'])} |"]
    load = m["load"]
    lines.append(f"| {load['clients']} clients asking for `/api/projects` at once | {load['requests_per_second']} requests/s, median {load['median_ms']} ms, p95 {load['p95_ms']} ms |")
    for busy in m["while_busy"]:
        what = "backup download(s)" if busy["kind"] == "backup" else "slow upload(s)"
        lines.append(f"| `GET /api/printers` while {busy['at_once']} {what} of {busy['long_ms']} ms run | "
                     f"median {busy['median_ms']} ms, slowest {busy['slowest_ms']} ms ({busy['reads']} reads) |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--models", type=int, default=300)
    parser.add_argument("--orders", type=int, default=600)
    parser.add_argument("--rolls", type=int, default=200)
    parser.add_argument("--customers", type=int, default=150)
    parser.add_argument("--images", type=int, default=120, help="models that have a photo and a cover picture")
    parser.add_argument("--image-edge", type=int, default=1024, help="pixels along the side of a product image")
    parser.add_argument("--env", action="append", default=[], metavar="NAME=VALUE", help="a variable for the server, e.g. WEB_CONCURRENCY=4")
    parser.add_argument("--json", help="also write the raw numbers to this file")
    args = parser.parse_args()
    size = {"models": args.models, "orders": args.orders, "rolls": args.rolls, "customers": args.customers, "images": args.images,
            "image_edge": args.image_edge}

    work = Path(tempfile.mkdtemp(prefix="pp-perf-"))
    server = None
    try:
        database_path, upload_dir = str(work / "perf.sqlite3"), str(work / "uploads")
        built = build(database_path, upload_dir, size)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = Server(work, database_path, upload_dir, port, dict(pair.split("=", 1) for pair in args.env))
        measured = {"api": measure_api(server, built["token"])}
        measured["browser"] = measure_browser(server, built["token"], built["model_id"])
        measured["editor_data"] = measure_editor_data(server, built["token"], measured["browser"].pop("editor_paths"))
        measured["load"] = measure_load(server, built["token"])
        measured["while_busy"] = [measure_while_busy(server, built["token"], n, kind) for kind in ("backup", "upload") for n in (1, 2)]
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "unknown"
        result = {"date": datetime.now(timezone.utc).date().isoformat(), "commit": commit,
                  "machine": f"{os.cpu_count()} CPUs, Python {platform.python_version()}, SQLite {sqlite3.sqlite_version}, {platform.system()} {platform.machine()}",
                  "gunicorn": server.flags, "data": size, "image_bytes": built["image_bytes"], "database_mb": built["database_mb"], "measured": measured}
        print(report(result))
        if args.json:
            Path(args.json).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    finally:
        if server:
            server.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
