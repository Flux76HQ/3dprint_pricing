"""3D Print Pricing: Flask application factory."""
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from . import api, auth, files, push, push_api
from .config import Config, load_config
from .db import make_pool
from .http import ApiError, error_response

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
                raise ApiError(403, "Origin niet toegestaan.")

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
    app.register_blueprint(files.bp)
    app.register_blueprint(push_api.bp)
    app.register_error_handler(ApiError, error_response)

    if cfg.push_configured and not app.testing and os.environ.get("PUSH_WORKER", "on") != "off":
        push.start_outbox_worker(app)          # delivers notifications held back by quiet hours

    @app.errorhandler(404)
    def _not_found(_):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Niet gevonden."}), 404
        return _spa()

    @app.errorhandler(413)
    def _too_large(_):
        return jsonify({"error": f"Het bestand is groter dan {cfg.max_upload_mb} MB."}), 413

    @app.errorhandler(405)
    def _method(_):
        return jsonify({"error": "Methode niet toegestaan."}), 405

    @app.errorhandler(Exception)
    def _unexpected(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify({"error": exc.description}), exc.code
        app.logger.exception("Unhandled error")
        return jsonify({"error": "Er ging iets mis op de server."}), 500

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
        return jsonify({"version": VERSION, "commit": _commit()})

    def _spa():
        return send_from_directory(cfg.static_dir, "index.html", max_age=0)

    @app.get("/sw.js")
    def service_worker():
        """The worker file carries the release, so every release changes its bytes and browsers see an update."""
        source = (Path(cfg.static_dir) / "sw.js").read_text(encoding="utf-8")
        source = source.replace("const APP_VERSION = 'dev';", f"const APP_VERSION = '{VERSION} ({_commit()})';")
        response = app.response_class(source, mimetype="text/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def static_files(path):
        if path.startswith("api/"):
            return jsonify({"error": "Niet gevonden."}), 404
        target = Path(cfg.static_dir) / path
        if path and target.is_file():
            # Always revalidate (ETag -> cheap 304s): a max-age here left the previous release's
            # JS and CSS in the browser for up to that long after an update.
            return send_from_directory(cfg.static_dir, path, max_age=0)
        return _spa()

    return app
