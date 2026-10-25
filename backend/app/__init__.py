"""3D Print Pricing: Flask application factory."""
import hashlib
import os
import re
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from . import ai_images, api, auth, backup, bambu_catalog, customers, filament_library, files, invoice_logo, invoice_template, orders, password_api, push, push_api, system
from .config import Config, build_channel, load_config
from .db import make_pool
from .http import ApiError, error_response
from .i18n import tr

def _read_version() -> str:
    # /app/VERSION in the container, the repository root in a checkout.
    for parent in Path(__file__).resolve().parents[1:3]:
        if (parent / "VERSION").exists():
            return (parent / "VERSION").read_text().strip()
    return "dev"


VERSION = _read_version()


def _commit() -> str:
    """Short commit this image was built from (build arg GIT_COMMIT); "dev" for local runs."""
    return (os.environ.get("APP_COMMIT") or "dev")[:7]


_IMPORT = re.compile(r"""((?:\bfrom|\bimport)\s*\(?\s*)(["'])(\.{1,2}/[^"']+?\.js)\2""")
_TOUCH_ICON = re.compile(r'''(<link rel="apple-touch-icon"[^>]*href="/icons/[^"?]+\.png)\?v=[^"]*"''')
_ASSET = re.compile(r"""\b(src|href)="(/(?:js|css|icons)/[^"?]+\.(?:js|css|png))\"""")


def create_app(config: Config | None = None, pool=None) -> Flask:
    cfg = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = cfg
    app.config["MAX_CONTENT_LENGTH"] = (cfg.max_upload_mb + 1) * 1024 * 1024
    hops = int(os.environ.get("PROXY_HOPS", "0"))
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)
    app.extensions["pool"] = pool or make_pool(cfg.database_url)

    @app.before_request
    def _guard():
        auth.load_session()
        # State-changing calls must come from our own origin. Together with the
        # SameSite=Strict cookie this is the CSRF defence.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") not in cfg.rp_origins:
                raise ApiError(403, "err.origin")

    @app.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(backup.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(filament_library.bp)
    app.register_blueprint(bambu_catalog.bp)
    app.register_blueprint(customers.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(invoice_template.bp)
    app.register_blueprint(invoice_logo.bp)
    app.register_blueprint(push_api.bp)
    app.register_blueprint(password_api.bp)
    app.register_blueprint(ai_images.bp)
    app.register_blueprint(system.bp)
    app.register_error_handler(ApiError, error_response)

    if cfg.push_configured and not app.testing and os.environ.get("PUSH_WORKER", "on") != "off":
        push.start_outbox_worker(app)          # delivers notifications held back by quiet hours

    @app.errorhandler(404)
    def _not_found(_):
        if request.path.startswith("/api/"):
            return jsonify({"error": tr("err.not_found")}), 404
        return _spa()

    @app.errorhandler(413)
    def _too_large(_):
        return jsonify({"error": tr("err.too_large", mb=cfg.max_upload_mb)}), 413

    @app.errorhandler(405)
    def _method(_):
        return jsonify({"error": tr("err.method")}), 405

    @app.errorhandler(Exception)
    def _unexpected(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify({"error": exc.description}), exc.code
        app.logger.exception("Unhandled error")
        return jsonify({"error": tr("err.server")}), 500

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "version": VERSION, "commit": _commit()})

    @app.get("/readyz")
    def readyz():
        try:
            with app.extensions["pool"].connection() as conn:
                conn.execute("SELECT 1")
        except Exception:
            return jsonify({"status": "database unavailable"}), 503
        return jsonify({"status": "ready", "version": VERSION, "commit": _commit()})

    @app.get("/api/version")
    def version():
        return jsonify({"version": VERSION, "commit": _commit(), "channel": build_channel()})

    def _build() -> str:
        return f"{VERSION}-{_commit()}"

    def _stamped(relative: str):
        """index.html, scripts, styles and PNG icons with this release in every URL they load.

        A browser or proxy that keeps an old copy of a file (or an installed app that has been open for days)
        can only ever hold URLs of its own release, so a new release cannot be mixed with old scripts. The
        running build is also baked into js/build.js, so the page knows what it really loaded.
        """
        path = Path(cfg.static_dir) / relative
        text = path.read_text(encoding="utf-8")
        token = _build()
        if relative == "index.html":
            text = _ASSET.sub(lambda m: f'{m.group(1)}="{m.group(2)}?v={token}"', text)
            # The home screen icon is looked at when someone pins the page: iOS keeps an icon per URL, so this one URL is new
            # on every load and a pin always takes the icon of the moment.
            if build_channel() == "beta":
                # A beta build says so in the tab title and under its home screen icon, next to a stable install.
                text = text.replace("<title>3D Print Pricing</title>", "<title>3D Print Pricing (beta)</title>")
                text = text.replace('name="apple-mobile-web-app-title" content="PrintPricing"', 'name="apple-mobile-web-app-title" content="PrintPricing beta"')
            text = _TOUCH_ICON.sub(lambda m: f'{m.group(1)}?v={token}.{time.time_ns() // 1_000_000:x}"', text)
        else:
            text = _IMPORT.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}?v={token}{m.group(2)}", text)
            text = text.replace("export const BUILD = { version: 'dev', commit: 'dev', channel: 'stable' };",
                                f"export const BUILD = {{ version: '{VERSION}', commit: '{_commit()}', channel: '{build_channel()}' }};")
        response = app.response_class(text, mimetype="text/html" if relative.endswith(".html") else "text/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.set_etag(hashlib.sha1(text.encode("utf-8")).hexdigest())
        return response.make_conditional(request)

    def _spa():
        return _stamped("index.html")

    @app.get("/sw.js")
    def service_worker():
        """The worker file carries the release, so every release changes its bytes and browsers see an update."""
        source = (Path(cfg.static_dir) / "sw.js").read_text(encoding="utf-8")
        source = source.replace("const APP_VERSION = 'dev';", f"const APP_VERSION = '{VERSION} ({_commit()})';")
        response = app.response_class(source, mimetype="text/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    # Where browsers and iOS look when a page does not say: real images, never the app's HTML page.
    root_icons = {"apple-touch-icon.png": "icons/apple-touch-icon.png", "apple-touch-icon-precomposed.png": "icons/apple-touch-icon.png",
                  "favicon.ico": "icons/favicon-32.png"}
    asset_types = (".png", ".ico", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".js", ".css", ".json", ".map", ".txt", ".woff", ".woff2",
                   ".webmanifest")

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def static_files(path):
        if path.startswith("api/"):
            return jsonify({"error": tr("err.not_found")}), 404
        if path in root_icons and (Path(cfg.static_dir) / root_icons[path]).is_file():
            return send_from_directory(cfg.static_dir, root_icons[path], max_age=0)
        target = Path(cfg.static_dir) / path
        if path.startswith("js/") and path.endswith(".js") and target.is_file():
            return _stamped(path)
        if path and target.is_file():
            # Always revalidate (ETag -> cheap 304s): a max-age here left the previous release's
            # JS and CSS in the browser for up to that long after an update.
            return send_from_directory(cfg.static_dir, path, max_age=0)
        if path.lower().endswith(asset_types):
            return jsonify({"error": tr("err.not_found")}), 404        # a missing file is missing, not the app's HTML page
        return _spa()

    return app
