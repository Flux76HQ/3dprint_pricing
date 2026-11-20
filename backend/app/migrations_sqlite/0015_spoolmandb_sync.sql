-- The copy of SpoolmanDB that an administrator fetched with the sync button (Settings -> Filaments), at most once a day. One row: the whole list as
-- the snapshot that ships with the app is written (`spoolmandb.py`), when it was fetched, and a `version` that goes up with every sync, which is how
-- every worker of the web server notices that another one fetched a newer copy. Without a row the app uses the snapshot it shipped with.
-- It is reproducible from the internet, so it is not part of a backup (a restore falls back to the shipped snapshot until the next sync).
CREATE TABLE spoolmandb_sync (
    singleton  BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (singleton),
    version    INTEGER NOT NULL,
    synced_at  TIMESTAMP TEXT NOT NULL,
    document   TEXT NOT NULL
);
