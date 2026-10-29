-- The colour of a roll as a colour (#rrggbb), for the roll icons in the stock overview. Empty = not set: the screen then guesses from the
-- colour's name ("Black", "zwart", ...) and falls back to a neutral grey.
ALTER TABLE filament_spools ADD COLUMN colour_hex text NOT NULL DEFAULT '' CHECK (colour_hex = '' OR colour_hex ~ '^#[0-9a-f]{6}$');
