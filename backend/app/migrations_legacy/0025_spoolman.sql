-- Spoolman as the source of the rolls (https://github.com/Donkie/Spoolman). A roll that came from Spoolman keeps Spoolman's own spool
-- number here, so the next sync updates that roll instead of adding another; rolls typed in by hand have none. `spoolman_synced_at` is
-- when the roll was last read from Spoolman. Both are in a backup (the number, so a restore stays linked), the time is not.
ALTER TABLE filament_spools ADD COLUMN spoolman_id integer;
ALTER TABLE filament_spools ADD COLUMN spoolman_synced_at timestamptz;
CREATE UNIQUE INDEX filament_spools_spoolman_id ON filament_spools (spoolman_id) WHERE spoolman_id IS NOT NULL;

-- Filament used by a calculation that was booked but not yet reported to Spoolman (it was out of reach, or the app stopped in between).
-- Booking writes a row here in the same transaction as the booking itself and sends it afterwards; a sync sends what is left first, and
-- counts what is left against the weight Spoolman reports until it is sent. Work in progress, not what the owner entered: not in a backup.
CREATE TABLE spoolman_pending_use (
    id           bigserial PRIMARY KEY,
    spoolman_id  integer NOT NULL,
    grams        numeric(10,1) NOT NULL CHECK (grams > 0),
    created_at   timestamptz NOT NULL DEFAULT now()
);
