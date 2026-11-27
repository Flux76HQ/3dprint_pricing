-- What each Bambu Lab invoice that was read in brought: one row per import, one row per invoice line (the filament, how many the invoice says, how many went
-- onto the shelf, at what price, and what happened to the library), so that the owner can check an import against the invoice afterwards, and so that the same
-- invoice is recognised when it is read in again. An import is a record, never edited: a second import of the same invoice is a second row, on purpose.
--
-- `invoice_number` / `order_number` are what the invoice says ('' when it does not say). `invoice_total` is the total of the invoice and `lines_total` what its
-- lines add up to (both including VAT, as the invoice has them), so a difference shows. `rolls_added` is the number of rolls that went onto the shelf in all.
-- On a line: `quantity` is what the invoice says, `rolls_added` what the owner let go onto the shelf (0 = none), `paid_price` the price per roll excluding VAT after
-- the discount, `list_price` the shop's price per roll excluding VAT (the library's reference price), `library` what happened to the filament in the library:
-- added, updated (it lacked something), unchanged, or skipped (the line was left out of the library).
CREATE TABLE invoice_imports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number  TEXT NOT NULL DEFAULT '',
    order_number    TEXT NOT NULL DEFAULT '',
    invoice_date    DATE TEXT,
    invoice_total   NUM2 CHECK (invoice_total >= 0),
    lines_total     NUM2 CHECK (lines_total >= 0),
    rolls_added     INTEGER NOT NULL DEFAULT 0 CHECK (rolls_added >= 0),
    imported_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE INDEX invoice_imports_invoice ON invoice_imports (invoice_number) WHERE invoice_number <> '';
CREATE INDEX invoice_imports_order ON invoice_imports (order_number) WHERE order_number <> '';

CREATE TABLE invoice_import_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id       INTEGER NOT NULL REFERENCES invoice_imports (id) ON DELETE CASCADE,
    position        INTEGER NOT NULL CHECK (position >= 1),
    brand           TEXT NOT NULL,
    product_type    TEXT NOT NULL DEFAULT '',
    material        TEXT NOT NULL DEFAULT '',
    colour          TEXT NOT NULL DEFAULT '',
    refill          BOOLEAN NOT NULL DEFAULT 0,
    sku             TEXT NOT NULL DEFAULT '',
    filament_id     TEXT NOT NULL DEFAULT '',
    barcode         TEXT NOT NULL DEFAULT '',
    roll_weight_g   NUM1 NOT NULL CHECK (roll_weight_g > 0),
    diameter_mm     NUM2 NOT NULL CHECK (diameter_mm > 0),
    quantity        INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    rolls_added     INTEGER NOT NULL DEFAULT 0 CHECK (rolls_added >= 0),
    paid_price      NUM2 CHECK (paid_price >= 0),
    list_price      NUM2 CHECK (list_price >= 0),
    library         TEXT NOT NULL CHECK (library IN ('added', 'updated', 'unchanged', 'skipped'))
);
CREATE INDEX invoice_import_lines_import ON invoice_import_lines (import_id, position);
