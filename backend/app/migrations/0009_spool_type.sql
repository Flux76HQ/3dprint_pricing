-- Brand and type of a filament roll are separate things ("Bambu Lab" + "Matte"). Existing rolls keep
-- whatever was typed into the brand field; the type starts empty.
ALTER TABLE filament_spools ADD COLUMN product_type text NOT NULL DEFAULT '';
