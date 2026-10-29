-- The invoice layout of the example invoice: a customer number and a subject ("Betreft") per order, and the logo that is shown
-- at the top left of the invoice (a PNG or JPEG, at most one; the file itself is under UPLOAD_DIR like every upload).
ALTER TABLE orders ADD COLUMN customer_number text NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN subject text NOT NULL DEFAULT '';

CREATE TABLE invoice_logo (
    id           boolean PRIMARY KEY DEFAULT true CHECK (id),
    filename     text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('png', 'jpeg')),
    stored_name  text NOT NULL,
    size_bytes   integer NOT NULL,
    sha256       text NOT NULL,
    width_px     integer NOT NULL,
    height_px    integer NOT NULL,
    uploaded_at  timestamptz NOT NULL DEFAULT now()
);
