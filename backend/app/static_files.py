"""The app's own files (`frontend/`): stamped with the release once, compressed once, and kept by the browser for as long as the release lives.

Every script, style sheet and PNG icon that index.html or a module loads carries `?v=<version>-<commit>` (`stamped`), and so does what the
page fetches by that rule itself (the language files). A URL with the *running* release in it never changes its bytes, so it is answered
`immutable`: a browser asks for it once per release, not at every launch. Everything else is `no-cache` (kept, but checked with its ETag
before every use): index.html and sw.js, which are how a new release is noticed; a URL without the release; a URL of *another* release (an
installed app that was open during an update: what the server has now is not what that URL meant, and must not be kept under it); and every
file of a development build (`commit == "dev"`), whose files change under the same name.

Stamping (read, two regular expressions, a hash) and compressing happen once per process and file, not per request (`Assets.text`). The
memo is keyed by the release and the channel and is checked against the file's size and modification time, so a changed file or a changed
build is never answered from memory; nothing a factory reset removes is kept here.
"""
import gzip
import hashlib
import mimetypes
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from flask import Response, request, send_from_directory
from werkzeug.security import safe_join

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
# What is worth compressing: text. Images and fonts are compressed already.
TEXT = (".js", ".css", ".json", ".html", ".svg", ".webmanifest", ".txt", ".map")

_IMPORT = re.compile(r"""((?:\bfrom|\bimport)\s*\(?\s*)(["'])(\.{1,2}/[^"']+?\.js)\2""")
_TOUCH_ICON = re.compile(r'''(<link rel="apple-touch-icon"[^>]*href="/icons/[^"?]+\.png)\?v=[^"]*"''')
_ASSET = re.compile(r"""\b(src|href)="(/(?:js|css|icons)/[^"?]+\.(?:js|css|png))\"""")


@dataclass(frozen=True)
class Build:
    version: str
    commit: str
    channel: str

    @property
    def token(self) -> str:
        return f"{self.version}-{self.commit}"


@dataclass(frozen=True)
class Asset:
    body: bytes
    packed: bytes                 # the same bytes, gzip
    etag: str
    mimetype: str


def stamped(relative: str, text: str, build: Build) -> str:
    """index.html and scripts with this release in every URL they load, and the running build baked into js/build.js.

    A browser or proxy that keeps an old copy of a file (or an installed app that has been open for days) can only ever hold URLs of
    its own release, so a new release cannot be mixed with old scripts, and the page knows what it really loaded.
    """
    if relative == "index.html":
        text = _ASSET.sub(lambda m: f'{m.group(1)}="{m.group(2)}?v={build.token}"', text)
        if build.channel == "beta":
            # A beta build says so in the tab title and under its home screen icon, next to a stable install.
            text = text.replace("<title>3D Print Pricing</title>", "<title>3D Print Pricing (beta)</title>")
            text = text.replace('name="apple-mobile-web-app-title" content="PrintPricing"', 'name="apple-mobile-web-app-title" content="PrintPricing beta"')
        return text
    if relative == "sw.js":
        # The worker file carries the release, so every release changes its bytes and browsers see an update.
        return text.replace("const APP_VERSION = 'dev';", f"const APP_VERSION = '{build.version} ({build.commit})';")
    if relative.startswith("js/") and relative.endswith(".js"):
        text = _IMPORT.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}?v={build.token}{m.group(2)}", text)
        return text.replace("export const BUILD = { version: 'dev', commit: 'dev', channel: 'stable' };",
                            f"export const BUILD = {{ version: '{build.version}', commit: '{build.commit}', channel: '{build.channel}' }};")
    return text


def packed(body: bytes) -> bytes:
    return gzip.compress(body, compresslevel=9, mtime=0)


class Assets:
    """Serves `static_dir`. One per app; what it remembers is derived from the files only."""

    def __init__(self, static_dir: str):
        self.root = Path(static_dir)
        self._memo: dict = {}
        self._lock = threading.Lock()

    def path(self, relative: str) -> "Path | None":
        """The file a URL path names, or None: never one outside `static_dir`, whatever the path says (`..`, an absolute path)."""
        joined = safe_join(str(self.root), relative) if relative else None
        return Path(joined) if joined and Path(joined).is_file() else None

    def text(self, relative: str, build: Build) -> Asset:
        """A text file as it is served, stamped and compressed the first time it is asked for and whenever the file or the build changed."""
        path = self.path(relative)
        if path is None:
            raise FileNotFoundError(relative)
        stat = path.stat()
        key, state = (relative, build), (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            hit = self._memo.get(key)
        if hit and hit[0] == state:
            return hit[1]
        body = stamped(relative, path.read_text(encoding="utf-8"), build).encode("utf-8")
        mimetype = "text/javascript" if relative.endswith(".js") else "text/html" if relative.endswith(".html") else \
            (mimetypes.guess_type(relative)[0] or "text/plain")
        asset = Asset(body, packed(body), hashlib.sha1(body).hexdigest(), mimetype)
        with self._lock:                                      # two requests that are both first both do the work; the answers are the same
            self._memo[key] = (state, asset)
        return asset

    @staticmethod
    def of_release(build: Build) -> bool:
        """Is this request for a URL of the running release? Only then may the answer be kept without asking again."""
        return build.commit != "dev" and request.args.get("v") == build.token

    def respond(self, asset: Asset, cache_control: str) -> Response:
        zipped = "gzip" in request.accept_encodings
        response = Response(asset.packed if zipped else asset.body, mimetype=asset.mimetype)
        if zipped:
            response.headers["Content-Encoding"] = "gzip"
        response.headers["Vary"] = "Accept-Encoding"
        response.headers["Cache-Control"] = cache_control
        response.set_etag(asset.etag + ("-gzip" if zipped else ""))      # the two forms are different bytes, so different validators
        return response.make_conditional(request)

    def index(self, build: Build) -> Response:
        """index.html. The home screen icon is looked at when someone pins the page: iOS keeps an icon per URL, so that one URL is new
        on every load and a pin always takes the icon of the moment. The rest of the page is stamped once."""
        base = self.text("index.html", build)
        text = _TOUCH_ICON.sub(lambda m: f'{m.group(1)}?v={build.token}.{time.time_ns() // 1_000_000:x}"', base.body.decode("utf-8"))
        body = text.encode("utf-8")
        return self.respond(Asset(body, gzip.compress(body, compresslevel=6, mtime=0), hashlib.sha1(body).hexdigest(), base.mimetype), REVALIDATE)

    def file(self, relative: str, build: Build) -> Response:
        """Any other file under `static_dir` (the caller has checked that it is one)."""
        keep = IMMUTABLE if self.of_release(build) else REVALIDATE
        if relative.lower().endswith(TEXT):
            return self.respond(self.text(relative, build), keep)
        # Always revalidate (ETag -> cheap 304s) unless the URL names this release: a max-age on a plain URL left the
        # previous release's files in the browser for up to that long after an update.
        response = send_from_directory(self.root, relative, max_age=31536000 if keep is IMMUTABLE else 0)
        response.headers["Cache-Control"] = keep
        return response
