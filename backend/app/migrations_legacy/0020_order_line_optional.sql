-- An optional line is an extra the customer does not need for the product to work (an accessory such as a cable or charger).
-- It is billed like any other line, but the invoice lists it apart from the product lines.
ALTER TABLE order_lines ADD COLUMN optional boolean NOT NULL DEFAULT false;
