-- A roll or a library entry that was picked from SpoolmanDB (https://github.com/Donkie/SpoolmanDB, MIT) keeps that filament's id there: the
-- reference to the source of its data. Empty for everything that was typed in. It is a reference, not a copy: the density and the weight of
-- an empty spool stay in the snapshot that ships with the app (`spoolmandb.py`) and are looked up by this id when the filament goes to Spoolman,
-- which is also where the id goes, as the filament's `external_id`.
ALTER TABLE filament_spools ADD COLUMN spoolmandb_id TEXT NOT NULL DEFAULT '';
ALTER TABLE filament_library ADD COLUMN spoolmandb_id TEXT NOT NULL DEFAULT '';
