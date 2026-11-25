-- Groups of rolls: a bin, a shelf, a drawer, a dry box, the AMS of a printer: wherever the rolls are kept (`filament_groups.py`). A roll is in at most one
-- group, and the group is what the roll lists can be filtered on.
--
-- Spoolman calls the same thing a spool's *location*, a plain text that every spool carries. A group here is that text with a row of its own, so that a
-- bin can exist before there is a roll in it, can be renamed in one go and can be offered in a pull-down. A group is found by its name, in either upper or
-- lower case, the way Spoolman reads a location, so the name is unique case-insensitively (SQLite folds the letters of ASCII only, which is all `lower` does).
--
-- A group is never removed from under a roll: the screens and the API only delete an empty one. `ON DELETE SET NULL` is what the database does if it
-- ever happens anyway (a roll without a group is a roll that is nowhere in particular, not a lost roll).
CREATE TABLE filament_groups (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE UNIQUE INDEX filament_groups_name ON filament_groups (lower(name));

ALTER TABLE filament_spools ADD COLUMN group_id UUID TEXT REFERENCES filament_groups(id) ON DELETE SET NULL;
CREATE INDEX filament_spools_group ON filament_spools (group_id) WHERE group_id IS NOT NULL;
