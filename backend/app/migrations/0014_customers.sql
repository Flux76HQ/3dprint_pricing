-- Customers: a customer has a number (the "klantnummer" that used to be typed into every order), contact details and a note. An order
-- points at its customer and keeps a copy of the details as they were when it was saved (so an invoice that went out never changes
-- behind your back); editing a customer updates the copy in its orders that have no invoice yet.
CREATE TABLE customers (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    number       text NOT NULL,
    name         text NOT NULL,
    address      text NOT NULL DEFAULT '',
    postal_code  text NOT NULL DEFAULT '',
    city         text NOT NULL DEFAULT '',
    country      text NOT NULL DEFAULT '',
    email        text NOT NULL DEFAULT '',
    phone        text NOT NULL DEFAULT '',
    notes        text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX customers_number_key ON customers (lower(number));
CREATE INDEX customers_name_idx ON customers (lower(name));

ALTER TABLE orders ADD COLUMN customer_id uuid REFERENCES customers (id) ON DELETE RESTRICT;
CREATE INDEX orders_customer_idx ON orders (customer_id);

-- The orders that exist get a customer: one per distinct name + customer number. A number that is empty or already taken by another
-- customer is replaced by the next free whole number, in the customer and in its orders.
DO $$
DECLARE
    r record;
    candidate text;
    next_no integer := 1;
    new_id uuid;
BEGIN
    FOR r IN
        SELECT DISTINCT ON (lower(customer_name), customer_number) customer_name, customer_number, address, postal_code, city, country,
               email, phone
          FROM orders
         ORDER BY lower(customer_name), customer_number, order_date DESC, created_at DESC
    LOOP
        candidate := r.customer_number;
        IF candidate = '' OR EXISTS (SELECT 1 FROM customers WHERE lower(number) = lower(candidate)) THEN
            LOOP
                candidate := next_no::text;
                next_no := next_no + 1;
                EXIT WHEN NOT EXISTS (SELECT 1 FROM customers WHERE lower(number) = lower(candidate))
                      AND NOT EXISTS (SELECT 1 FROM orders WHERE lower(customer_number) = lower(candidate));
            END LOOP;
        END IF;
        INSERT INTO customers (number, name, address, postal_code, city, country, email, phone)
        VALUES (candidate, r.customer_name, r.address, r.postal_code, r.city, r.country, r.email, r.phone)
        RETURNING id INTO new_id;
        UPDATE orders SET customer_id = new_id, customer_number = candidate
         WHERE lower(customer_name) = lower(r.customer_name) AND customer_number = r.customer_number;
    END LOOP;
END $$;

ALTER TABLE orders ALTER COLUMN customer_id SET NOT NULL;
