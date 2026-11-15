-- The live view of a Bambu Lab printer through the Bambu cloud (`bambu_live.py`): which roll is in which slot of the AMS.
--
-- A sync of the Filament Manager (`bambu_cloud.sync`) keeps two traces of each spool here, so that a slot the printer reports can be told to be that roll:
-- `bambu_tag`, the SHA-256 of the RFID chip of a Bambu spool (never the chip's number itself), and `bambu_slot`, where the Filament Manager last saw the
-- spool ("<serial>/<AMS>/<slot>", as Bambu Studio or Handy last reported it). Both are the cloud's and come back with the next sync, so neither is in a backup.
ALTER TABLE filament_spools ADD COLUMN bambu_tag TEXT NOT NULL DEFAULT '';
ALTER TABLE filament_spools ADD COLUMN bambu_slot TEXT NOT NULL DEFAULT '';
