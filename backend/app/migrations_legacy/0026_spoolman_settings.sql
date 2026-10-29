-- The address of Spoolman, typed in under Settings -> Filaments by an administrator. `SPOOLMAN_URL` in `.env` wins when it is set (the person who runs
-- the installation can fix the address there, and the screen then shows it read-only); this is for everybody else. One row at most. It is not in a
-- backup: an address is a fact about one network, and a backup restored on another installation must not point it at the wrong machine.
CREATE TABLE spoolman_settings (
    singleton  boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    url        text NOT NULL DEFAULT ''
);
