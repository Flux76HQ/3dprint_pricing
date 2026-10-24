-- Margin and rounding belong to the order: a line made from a calculation keeps that calculation's cost price (excl. VAT) and its own
-- margin, and the order says how the price incl. VAT is rounded. The price per piece of such a line is worked out on the server from
-- those; a line without a cost price (a free line, or one made before this) keeps the price it was typed or copied with.
ALTER TABLE orders ADD COLUMN price_rounding text NOT NULL DEFAULT 'none'
    CHECK (price_rounding IN ('none', '0.05', '0.10', '0.50', '1.00', '5.00', 'x.95', 'x.99'));
ALTER TABLE order_lines
    ADD COLUMN cost_price numeric(12,2) CHECK (cost_price >= 0),
    ADD COLUMN margin_pct numeric(6,2) CHECK (margin_pct >= 0);
