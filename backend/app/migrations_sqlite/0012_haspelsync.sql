-- HaspelSync (https://github.com/Rdiger-36/HaspelSync) shows the running print and the filament of a Bambu Lab printer, which this app
-- puts on the Printers page.
--
-- A printer here can name the printer of HaspelSync it is, by its serial number (as HaspelSync keeps it: upper case). One printer of
-- HaspelSync belongs to at most one printer here, and the database insists on it.
ALTER TABLE printers ADD COLUMN haspelsync_serial TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX printers_haspelsync_serial ON printers (haspelsync_serial) WHERE haspelsync_serial <> '';

-- Where HaspelSync is, and the API key its address needs. The key has to be readable to be sent, so it is sealed (passwords.seal), never
-- returned and never part of a backup; the address describes one network and is not in a backup either. `HASPELSYNC_URL` and
-- `HASPELSYNC_API_KEY` in .env go before what is typed here.
CREATE TABLE haspelsync_settings (
    singleton    BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (singleton),
    url          TEXT NOT NULL DEFAULT '',
    api_key_enc  TEXT
);
