-- An order line made from a 3D model takes the model's selling price as its price, and an extra margin can be added on top of it.
--
-- `base_price`: the price per piece, including VAT, that the line starts from: the calculation's selling price (with the rounding the calculation
-- has) minus the accessories that become lines of their own, as it was when the line was added. NULL on every line there was before this
-- migration and on every line that is not a model's: those are priced as they always were (from `cost_price`, `margin_pct` and the rounding of the
-- order), so no order and no invoice changes. On a line with a `base_price`, `margin_pct` is the extra margin on top of it, in percent.
-- `price_rounding`: the rounding the calculation had when the line was added, one of the roundings of the calculation; the extra margin is
-- rounded with it. NULL = the rounding of the order.
-- `cost_price` stays the cost, whatever the price is made of: the sales overview (revenue, cost, margin) reads it.

ALTER TABLE order_lines ADD COLUMN base_price NUM2 CHECK (base_price >= 0);
ALTER TABLE order_lines ADD COLUMN price_rounding TEXT CHECK (price_rounding IN ('none', '0.05', '0.10', '0.50', '1.00', '5.00', 'x.95', 'x.99'));
