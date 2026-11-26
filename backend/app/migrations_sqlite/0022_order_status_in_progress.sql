-- foreign_keys: off
-- An order gets a status between "nieuw" and "verwerkt": "in_behandeling" (in progress). The status is a CHECK on the table, and SQLite cannot
-- change a CHECK, so `orders` is built again the way SQLite documents (https://www.sqlite.org/lang_altertable.html, "Making Other Kinds Of
-- Table Schema Changes"): the new table, the rows copied as they are, the old table dropped, the new one renamed, the indexes made again.
--
-- The line above is read by the runner (`db.run_migrations`): it switches foreign keys off for this migration (that cannot be done inside the
-- transaction), because `order_lines` and `invoice_pdfs` point at `orders` with ON DELETE CASCADE and dropping the old table would otherwise
-- delete every line and every made invoice with it. Before the commit the runner checks that no foreign key is broken, and rolls back if one is.
-- Every column is named on both sides of the copy: nothing depends on the order of the columns, and a column that is not named is not copied.

CREATE TABLE orders_new (
    id              UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    number          INTEGER NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'nieuw' CHECK (status IN ('nieuw', 'in_behandeling', 'verwerkt', 'verstuurd', 'afgehandeld')),
    order_date      DATE TEXT NOT NULL DEFAULT (date('now')),
    delivery_date   DATE TEXT,
    customer_name   TEXT NOT NULL,
    address         TEXT NOT NULL DEFAULT '',
    postal_code     TEXT NOT NULL DEFAULT '',
    city            TEXT NOT NULL DEFAULT '',
    country         TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    invoice_number  TEXT UNIQUE,
    invoice_date    DATE TEXT,
    created_at      TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at      TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    customer_number TEXT NOT NULL DEFAULT '',
    subject         TEXT NOT NULL DEFAULT '',
    customer_id     UUID TEXT NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    price_rounding  TEXT NOT NULL DEFAULT 'none' CHECK (price_rounding IN ('none', '0.05', '0.10', '0.50', '1.00', '5.00', 'x.95', 'x.99'))
);

INSERT INTO orders_new (id, number, status, order_date, delivery_date, customer_name, address, postal_code, city, country, email, phone, notes,
                        invoice_number, invoice_date, created_at, updated_at, customer_number, subject, customer_id, price_rounding)
SELECT id, number, status, order_date, delivery_date, customer_name, address, postal_code, city, country, email, phone, notes,
       invoice_number, invoice_date, created_at, updated_at, customer_number, subject, customer_id, price_rounding
FROM orders;

DROP TABLE orders;
ALTER TABLE orders_new RENAME TO orders;

CREATE INDEX orders_order_date_idx ON orders (order_date DESC);
CREATE INDEX orders_customer_idx ON orders (customer_id);
