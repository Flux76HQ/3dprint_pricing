-- Identification and print settings of a filament roll. The barcode identifies the *product*
-- (every roll of the same filament carries the same EAN), so it is deliberately not unique.
ALTER TABLE filament_spools ADD COLUMN barcode      text NOT NULL DEFAULT '';
ALTER TABLE filament_spools ADD COLUMN diameter_mm  numeric(4,2) NOT NULL DEFAULT 1.75
    CHECK (diameter_mm > 0 AND diameter_mm <= 5);
ALTER TABLE filament_spools ADD COLUMN print_temp_c smallint CHECK (print_temp_c BETWEEN 0 AND 500);
ALTER TABLE filament_spools ADD COLUMN bed_temp_c   smallint CHECK (bed_temp_c BETWEEN 0 AND 200);
CREATE INDEX filament_spools_barcode ON filament_spools (barcode) WHERE barcode <> '';
