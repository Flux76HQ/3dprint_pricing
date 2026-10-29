-- The uploaded invoice template and logo live in the database from now on (bytes included), so they survive whatever happens to the
-- uploads folder of the container. Rows made by earlier releases keep their file name until the file has been moved into the database
-- (the first time it is read); `stored_name` is empty from then on.
ALTER TABLE invoice_template ADD COLUMN content bytea;
ALTER TABLE invoice_template ALTER COLUMN stored_name DROP NOT NULL;
ALTER TABLE invoice_logo ADD COLUMN content bytea;
ALTER TABLE invoice_logo ALTER COLUMN stored_name DROP NOT NULL;

-- The invoice as it was made: one PDF per order, kept so it can be downloaded again exactly as it was sent. Making the invoice again
-- (after a change to the order) replaces it.
CREATE TABLE invoice_pdfs (
    order_id        uuid PRIMARY KEY REFERENCES orders (id) ON DELETE CASCADE,
    invoice_number  text NOT NULL,
    content         bytea NOT NULL,
    size_bytes      integer NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
