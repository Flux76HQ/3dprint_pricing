-- Orders: a customer's order of several prints, with the dates, the customer's name and address, the lines (each linked to a
-- calculation, or free) and the status. An invoice can be made from an order; it gets its number once and keeps it.

-- A calculation gets a number to find it by ("model 12"). Existing ones are numbered in the order they were made.
CREATE SEQUENCE project_number_seq;
ALTER TABLE projects ADD COLUMN number integer;
UPDATE projects p SET number = n.rn FROM (SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn FROM projects) n WHERE p.id = n.id;
SELECT setval('project_number_seq', COALESCE((SELECT max(number) FROM projects), 0) + 1, false);
ALTER TABLE projects ALTER COLUMN number SET DEFAULT nextval('project_number_seq'), ALTER COLUMN number SET NOT NULL;
ALTER SEQUENCE project_number_seq OWNED BY projects.number;
CREATE UNIQUE INDEX projects_number_key ON projects (number);

CREATE SEQUENCE order_number_seq;
CREATE TABLE orders (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    number         integer NOT NULL UNIQUE DEFAULT nextval('order_number_seq'),
    status         text NOT NULL DEFAULT 'nieuw' CHECK (status IN ('nieuw', 'verwerkt', 'verstuurd', 'afgehandeld')),
    order_date     date NOT NULL DEFAULT current_date,
    delivery_date  date,
    customer_name  text NOT NULL,
    address        text NOT NULL DEFAULT '',
    postal_code    text NOT NULL DEFAULT '',
    city           text NOT NULL DEFAULT '',
    country        text NOT NULL DEFAULT '',
    email          text NOT NULL DEFAULT '',
    phone          text NOT NULL DEFAULT '',
    notes          text NOT NULL DEFAULT '',
    invoice_number text UNIQUE,
    invoice_date   date,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
ALTER SEQUENCE order_number_seq OWNED BY orders.number;
CREATE INDEX orders_order_date_idx ON orders (order_date DESC);

-- `unit_price` is what the customer pays per piece including VAT (the price the calculation shows); the VAT is taken out
-- of the totals per rate, never added on top. The description and price are copied when the line is made, so a later
-- change to the calculation does not rewrite an order that was agreed (or invoiced).
CREATE TABLE order_lines (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    position        integer NOT NULL,
    project_id      uuid REFERENCES projects(id) ON DELETE SET NULL,
    project_number  integer,
    description     text NOT NULL,
    quantity        integer NOT NULL CHECK (quantity >= 1),
    unit_price      numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    vat_pct         numeric(5,2) NOT NULL DEFAULT 0 CHECK (vat_pct >= 0 AND vat_pct <= 100)
);
CREATE INDEX order_lines_order_idx ON order_lines (order_id, position);

-- Invoice numbers are "<year>-<4 digits>", counted per year; claimed atomically so two requests never get the same one.
CREATE TABLE invoice_counters (
    year  integer PRIMARY KEY,
    last  integer NOT NULL
);

-- The invoice template the owner uploaded (a Word file with placeholders, or a PDF used as letter paper). At most one; the file
-- itself is under UPLOAD_DIR like every upload.
CREATE TABLE invoice_template (
    id                 boolean PRIMARY KEY DEFAULT true CHECK (id),
    filename           text NOT NULL,
    kind               text NOT NULL CHECK (kind IN ('docx', 'pdf')),
    stored_name        text NOT NULL,
    size_bytes         integer NOT NULL,
    sha256             text NOT NULL,
    margin_top_mm      integer NOT NULL DEFAULT 55 CHECK (margin_top_mm BETWEEN 0 AND 200),
    margin_bottom_mm   integer NOT NULL DEFAULT 25 CHECK (margin_bottom_mm BETWEEN 0 AND 200),
    uploaded_at        timestamptz NOT NULL DEFAULT now()
);
