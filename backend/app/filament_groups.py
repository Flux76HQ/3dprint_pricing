"""Groups of rolls: the bin, shelf, drawer, dry box or AMS a roll is kept in (migration 0019).

A roll is in at most one group (`filament_spools.group_id`) and the roll lists can be filtered on it. A group is found by its name, in upper or
lower case alike: that is how Spoolman reads a *location*, which is what a group is there (a text on each spool, `spoolman.location_of`). So a group
and a Spoolman location are the same thing, and keeping them in step is `spoolman.sync` (Spoolman's location becomes the roll's group),
`assign` below (a roll moved here is moved in Spoolman first, while Spoolman is in use) and `spoolman.push_groups`.

A group is never removed from under a roll: only an empty one can be deleted (`group.not_empty`), because a roll that is in a group in Spoolman
would bring the group back at the next sync. Nothing here ever deletes a roll.
"""
import logging
import uuid

from flask import Blueprint, jsonify

from .db import UniqueViolation, id_list, named_lock
from .http import ApiError, json_body, login_required, pool
from .i18n import L

log = logging.getLogger(__name__)
bp = Blueprint("filament_groups", __name__, url_prefix="/api/groups")

NAME_MAX = 64                       # what Spoolman accepts for a location
MAX_ASSIGN = 200                    # rolls moved in one request: each one that comes from Spoolman is a call to it, and the screen waits

# The rolls with the name of their group (empty for none): what every list of rolls reads, so the screens never need a second question.
SPOOLS_WITH_GROUP = ("SELECT s.*, COALESCE(g.name, '') AS group_name FROM filament_spools s LEFT JOIN filament_groups g ON g.id = s.group_id")


@bp.before_request
@login_required
def _guard():
    """Every route here needs a session. Groups are the everyday work of whoever keeps the shelf, so they are not for administrators only."""


def clean(value, *, required: bool = True) -> str:
    """A group's name as it is stored: trimmed, at most `NAME_MAX` characters. Empty is no group (when `required` is off)."""
    name = "" if value is None else str(value).strip()
    if required and not name:
        raise ApiError(400, "err.required", label=L("f.group"))
    if len(name) > NAME_MAX:
        raise ApiError(400, "err.too_long", label=L("f.group"), max=NAME_MAX)
    return name


def find(conn, name: str):
    """The group with this name, whatever the case, or None."""
    return conn.execute("SELECT * FROM filament_groups WHERE lower(name) = lower(%s)", (name,)).fetchone()


def ensure(conn, name: str):
    """The id of the group with this name, made when it is new; None for no name. Inside a writing transaction, which holds the write lock, so
    two rolls that need the same new group make it once."""
    name = name.strip()
    if not name:
        return None
    found = find(conn, name)
    if found is not None:
        return found["id"]
    return conn.execute("INSERT INTO filament_groups (name) VALUES (%s) RETURNING id", (name[:NAME_MAX],)).fetchone()["id"]


def named(conn, row: dict) -> dict:
    """A roll as the lists give it: with the name of its group (`group_name`, empty for none)."""
    found = conn.execute("SELECT name FROM filament_groups WHERE id = %s", (row["group_id"],)).fetchone() if row["group_id"] is not None else None
    return {**row, "group_name": found["name"] if found else ""}


def listing(conn) -> list[dict]:
    """Every group with what is in it: the rolls that are not archived and the grams left on them (`rolls`, `remaining_g`), and how many rolls name
    it at all, archived ones too (`in_use`: a group with any cannot be deleted) and how many of them come from Spoolman (`from_spoolman`)."""
    from .api import _serialise                                 # imported here: that module imports this one
    groups = conn.execute("SELECT id, name, created_at FROM filament_groups ORDER BY lower(name), id").fetchall()
    found = {g["id"]: {**g, "rolls": 0, "in_use": 0, "from_spoolman": 0, "remaining_g": 0} for g in groups}
    for roll in conn.execute("SELECT group_id, archived, remaining_g, spoolman_id FROM filament_spools WHERE group_id IS NOT NULL").fetchall():
        group = found[roll["group_id"]]
        group["in_use"] += 1
        group["from_spoolman"] += roll["spoolman_id"] is not None
        if not roll["archived"]:
            group["rolls"] += 1
            group["remaining_g"] += roll["remaining_g"]            # added up here, not in SQL: a SUM would come back as a float
    return [_serialise({**g, "remaining_g": str(g["remaining_g"])}) for g in found.values()]


@bp.get("")
def list_groups():
    with pool().read() as conn:
        return jsonify(listing(conn))


@bp.post("")
def create_group():
    name = clean(json_body().get("name"))
    try:
        with pool().connection() as conn:
            found = find(conn, name)
            if found is not None:
                raise ApiError(409, "group.exists", name=found["name"])             # as it is spelled here, not as it was typed
            made = conn.execute("INSERT INTO filament_groups (name) VALUES (%s) RETURNING id", (name,)).fetchone()["id"]
            row = next(g for g in listing(conn) if g["id"] == str(made))
    except UniqueViolation:                                     # another request made it between the look and the insert
        raise ApiError(409, "group.exists", name=name) from None
    return jsonify(row), 201


@bp.patch("/<uuid:group_id>")
def rename_group(group_id):
    """Rename a group. A group that has rolls from Spoolman is renamed there first (all its spools move to the new location in one call), so the next
    sync does not bring the old name back; the new name may not be one that another group already has."""
    from . import spoolman                                      # imported here: that module imports this one
    name = clean(json_body().get("name"))
    on = spoolman.enabled()                                     # asked before the request holds a connection
    with pool().read() as conn:
        row = conn.execute("SELECT * FROM filament_groups WHERE id = %s", (group_id,)).fetchone()
        if row is None:
            raise ApiError(404, "err.not_found")
        clash = find(conn, name)
        if clash is not None and clash["id"] != row["id"]:
            raise ApiError(409, "group.exists", name=clash["name"])
        linked = conn.execute("SELECT 1 FROM filament_spools WHERE group_id = %s AND spoolman_id IS NOT NULL LIMIT 1", (group_id,)).fetchone()

    def save():
        with pool().connection() as conn:
            conn.execute("UPDATE filament_groups SET name = %s WHERE id = %s", (name, group_id))
            return next(g for g in listing(conn) if g["id"] == str(group_id))

    if row["name"] == name:
        with pool().read() as conn:
            return jsonify(next(g for g in listing(conn) if g["id"] == str(group_id)))
    try:
        if on and linked:
            with named_lock(pool(), spoolman.LOCK):             # not while a sync reads the old name
                spoolman.rename_location(row["name"], name)
                return jsonify(save())
        return jsonify(save())
    except spoolman.SpoolmanError as exc:
        raise exc.api() from None
    except UniqueViolation:
        raise ApiError(409, "group.exists", name=name) from None


@bp.post("/assign")
def assign_rolls():
    """Put the chosen rolls in a group (`group`, a name: made when it is new; empty takes them out of any group). Rolls from Spoolman are moved there
    too (see `assign`). Answers how many were moved: the ones that were in the group already are not counted."""
    from . import spoolman                                      # imported here: that module imports this one
    body = json_body()
    ids = body.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ApiError(400, "group.no_rolls")
    try:
        ids = [str(uuid.UUID(i)) for i in ids]
    except ValueError:
        raise ApiError(404, "err.not_found") from None
    on = spoolman.enabled()                                     # asked before the request holds a connection
    return jsonify({"moved": assign(ids, body.get("group"), spoolman_on=on)})


@bp.delete("/<uuid:group_id>")
def delete_group(group_id):
    with pool().connection() as conn:
        row = conn.execute("SELECT name FROM filament_groups WHERE id = %s", (group_id,)).fetchone()
        if row is None:
            raise ApiError(404, "err.not_found")
        in_use = conn.execute("SELECT count(*) AS n FROM filament_spools WHERE group_id = %s", (group_id,)).fetchone()["n"]
        if in_use:
            raise ApiError(409, "group.not_empty", name=row["name"], n=in_use)
        conn.execute("DELETE FROM filament_groups WHERE id = %s", (group_id,))
    return jsonify({"ok": True})


def assign(ids: list, name: str, *, spoolman_on: bool) -> int:
    """Put these rolls in the group `name` ('' = out of any group); how many were moved. The group is made when it is new.

    A roll that comes from Spoolman, while Spoolman is in use, is Spoolman's: its spool's location is changed there first (outside any transaction,
    under the sync's lock so a sync does not read the old one halfway), and only when Spoolman has taken it does the roll move here. A failure
    half way leaves the rolls moved so far moved, in both places, and the rest where they were: never a roll that is in one group here and in
    another there. Every other roll moves here only. Rolls that are in the group already are not touched (and cost Spoolman no call)."""
    from . import spoolman                                      # imported here: that module imports this one
    name = clean(name, required=False)
    wanted = list(dict.fromkeys(str(i) for i in ids))
    if not wanted:
        raise ApiError(400, "group.no_rolls")
    if len(wanted) > MAX_ASSIGN:
        raise ApiError(400, "group.too_many", max=MAX_ASSIGN)
    with pool().read() as conn:
        rolls = conn.execute("SELECT s.id, s.spoolman_id, COALESCE(g.name, '') AS group_name FROM filament_spools s LEFT JOIN filament_groups g ON g.id = s.group_id "
                             "WHERE s.id IN (SELECT value FROM json_each(%s))", (id_list(wanted),)).fetchall()
    if len(rolls) != len(wanted):
        raise ApiError(404, "err.not_found")
    todo = [r for r in rolls if r["group_name"].lower() != name.lower()]
    there = [r for r in todo if spoolman_on and r["spoolman_id"] is not None]
    here = [r for r in todo if r not in there]

    def move(batch):
        with pool().connection() as conn:
            conn.execute("UPDATE filament_spools SET group_id = %s WHERE id IN (SELECT value FROM json_each(%s))",
                         (ensure(conn, name), id_list([str(r["id"]) for r in batch])))

    try:
        if there:
            with named_lock(pool(), spoolman.LOCK):
                for roll in there:
                    spoolman.set_location(roll["spoolman_id"], name or None)
                    move([roll])
    except spoolman.SpoolmanError as exc:
        raise exc.api() from None
    if here:
        move(here)
    return len(todo)
