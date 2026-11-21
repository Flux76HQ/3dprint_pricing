"""Where the filament and the printers are read from: one **source** at a time, chosen by an administrator at the top of Settings -> Integrations.

A source is a set of connections (`SOURCES`): today **Spoolman + HaspelSync** (`spoolman`), or the **Bambu Lab cloud** (`bambu`: the Filament Manager
and the live view of the printers). Each connection asks one question, `uses(<its name>)`, and knows nothing of the others: `spoolman.enabled()`,
`haspelsync.enabled()` and `bambu_cloud.active()` are false while their source is not the chosen one. **Another printer set-up is one more entry here**
(its connections, and the order in which `_derived` recognises it) plus its cards in `frontend/js/sources.js`; nothing else asks which source it is.

The choice decides what is *used*, never what is *kept*: addresses, keys and sign-ins of a source that rests stay as they are, so switching back is one
choice. It is kept in `app_state` (`KEY`): like the addresses it describes this installation's connections, so it is not in a backup, and a factory reset
forgets it. **Until an administrator has chosen**, it follows from what is set up (`_derived`): the first source in `SOURCES` whose `recognise` sees its
connection set up, else `DEFAULT`.
"""
from flask import Blueprint, g, jsonify

from .http import ApiError, config, json_body, login_required, pool

bp = Blueprint("sources", __name__, url_prefix="/api/sources")

KEY = "filament_source"


def _spoolman_set(conn) -> bool:
    return bool(config().spoolman_url) or bool(conn.execute("SELECT 1 FROM spoolman_settings WHERE url <> ''").fetchone())


def _bambu_set(conn) -> bool:
    return bool(conn.execute("SELECT 1 FROM bambu_cloud_settings WHERE token_enc IS NOT NULL").fetchone())


# id -> the connections it uses, and how to recognise an installation that has it set up while nobody chose (tried in this order).
SOURCES = {
    "spoolman": {"uses": ("spoolman", "haspelsync"), "recognise": _spoolman_set},
    "bambu": {"uses": ("bambu_cloud",), "recognise": _bambu_set},
}
DEFAULT = "spoolman"                  # what every installation had before there was a choice


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session; changing the choice is for administrators (`access.ADMIN_ONLY`)."""


def _derived(conn) -> str:
    return next((name for name, source in SOURCES.items() if source["recognise"](conn)), DEFAULT)


def _read() -> tuple[str, bool]:
    """(the source in use, whether an administrator chose it), read once per request and before the request holds a connection of its own."""
    if getattr(g, "filament_source", None) is None:
        with pool().read() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = %s", (KEY,)).fetchone()
            chosen = row["value"] if row and row["value"] in SOURCES else None
            g.filament_source = (chosen, True) if chosen else (_derived(conn), False)
    return g.filament_source


def current() -> str:
    return _read()[0]


def uses(connection: str) -> bool:
    """Whether this connection belongs to the source in use. Every connection asks this, and nothing else, about the choice."""
    return connection in SOURCES[current()]["uses"]


def clear() -> None:
    """Forget what this request read (after a change of the choice, or of what it is derived from)."""
    for name in ("filament_source", "spoolman_address", "haspelsync", "bambu_cloud"):
        if getattr(g, name, None) is not None:
            setattr(g, name, None)


def _answer() -> dict:
    source, chosen = _read()
    return {"source": source, "chosen": chosen, "sources": [{"id": name, "uses": list(s["uses"])} for name, s in SOURCES.items()],
            "can_change": getattr(g, "role", None) == "admin"}


@bp.get("")
def show():
    return jsonify(_answer())


@bp.put("")
def choose():
    """An administrator chooses the source. Nothing is removed: what belongs to another source rests with its settings."""
    source = json_body().get("source")
    if not isinstance(source, str) or source not in SOURCES:
        raise ApiError(400, "sources.bad")
    with pool().connection() as conn:
        conn.execute("INSERT INTO app_state (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (KEY, source))
    clear()
    if "bambu_cloud" not in SOURCES[source]["uses"]:
        from . import bambu_live                           # imported here: it imports what asks this module
        bambu_live.close()                                 # this worker's live connection; another worker's closes when nobody asks for it
    return jsonify(_answer())
