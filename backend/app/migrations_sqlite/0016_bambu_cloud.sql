-- The Filament Manager of Bambu Lab (the spools a Bambu account keeps in the Bambu cloud, shown by Bambu Studio and Bambu Handy) as a source of the
-- rolls, for an installation without Spoolman (`bambu_cloud.py`). One source at a time: while a Spoolman is set, this one is not used.
--
-- A roll that is a spool of the Filament Manager names it by the cloud's own number. One spool is at most one roll, and the database insists.
ALTER TABLE filament_spools ADD COLUMN bambu_id INTEGER;
ALTER TABLE filament_spools ADD COLUMN bambu_synced_at TIMESTAMP TEXT;
CREATE UNIQUE INDEX filament_spools_bambu_id ON filament_spools (bambu_id) WHERE bambu_id IS NOT NULL;

-- The Bambu account the app is signed in to. The token has to be readable to be sent, so it is sealed (passwords.seal), never returned and never part
-- of a backup; the password is never stored. A login that waits for a code from the e-mail or the authenticator app keeps what it needs for that second
-- step in `pending_enc` (sealed too) until `pending_until`. None of this is in a backup: it is a sign-in, not data of the business.
CREATE TABLE bambu_cloud_settings (
    singleton      BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (singleton),
    region         TEXT NOT NULL DEFAULT 'global' CHECK (region IN ('global', 'china')),
    account        TEXT NOT NULL DEFAULT '',
    token_enc      TEXT,
    expires_at     TIMESTAMP TEXT,
    pending_enc    TEXT,
    pending_until  TIMESTAMP TEXT
);

-- What a calculation took off a roll of the Filament Manager and has not yet been written back to the cloud. Booking writes a row here in the same
-- transaction as the new weight of the roll; a flush (right after the booking, and first in every sync) subtracts it from the spool in the cloud and
-- deletes the row. Until then a sync subtracts it from the weight the cloud reports, so the shelf does not jump back up. Not in a backup.
CREATE TABLE bambu_cloud_pending_use (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bambu_id       INTEGER NOT NULL,
    grams          NUM1 NOT NULL CHECK (grams > 0),
    created_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    claimed_until  TIMESTAMP TEXT       -- a flush that is sending this one leaves it alone until then (a crash hands it back)
);
