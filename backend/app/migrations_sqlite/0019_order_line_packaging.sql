-- Packaging material on an order (a box, tape, filler) is marked as such: its price counts in the total of the order, but the line itself is never listed on
-- the invoice. Before this a line did not say what it was, so the lines that already exist stay as they are (not packaging): an invoice that went out is
-- never rewritten, and a guess from the name of a line would change the totals of orders that were not asked to change.
ALTER TABLE order_lines ADD COLUMN packaging BOOLEAN NOT NULL DEFAULT 0;
