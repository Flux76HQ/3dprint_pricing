-- The filament library: the specs of the filaments you buy (brand, type, colour, weight, diameter, temperatures, a reference price),
-- kept apart from the rolls on the shelf. A new roll can be made from an entry, so the specs are typed once. Filled by hand, from a
-- Bambu Lab invoice, or from a JSON file exported from another installation. `filament_id` is the supplier's own number for the colour
-- (Bambu Lab: 10103) and `sku` the shop's article number. An import matches an entry on its SKU, else its barcode, else its filament ID,
-- else brand, material, type, colour and refill.
CREATE TABLE filament_library (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand          text NOT NULL,
    product_type   text NOT NULL DEFAULT '',
    material       text NOT NULL DEFAULT '',
    colour         text NOT NULL DEFAULT '',
    colour_hex     text NOT NULL DEFAULT '' CHECK (colour_hex = '' OR colour_hex ~ '^#[0-9a-f]{6}$'),
    filament_id    text NOT NULL DEFAULT '',
    sku            text NOT NULL DEFAULT '',
    barcode        text NOT NULL DEFAULT '',
    refill         boolean NOT NULL DEFAULT false,
    roll_weight_g  numeric(10,1) NOT NULL DEFAULT 1000 CHECK (roll_weight_g > 0),
    diameter_mm    numeric(4,2) NOT NULL DEFAULT 1.75 CHECK (diameter_mm > 0),
    print_temp_c   smallint CHECK (print_temp_c BETWEEN 0 AND 500),
    bed_temp_c     smallint CHECK (bed_temp_c BETWEEN 0 AND 200),
    price          numeric(12,2) CHECK (price >= 0),
    notes          text NOT NULL DEFAULT '',
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX filament_library_sku ON filament_library (lower(brand), lower(sku)) WHERE sku <> '';
