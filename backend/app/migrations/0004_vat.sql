-- VAT rate charged on the selling price of a calculation. 0 means no VAT is shown
-- (also what every calculation saved before this migration had).
ALTER TABLE projects ADD COLUMN vat_pct numeric(5,2) NOT NULL DEFAULT 0 CHECK (vat_pct >= 0 AND vat_pct <= 100);

-- Round the selling price including VAT up to a "nice" amount; margin_pct then acts as a minimum.
ALTER TABLE projects ADD COLUMN price_rounding text NOT NULL DEFAULT 'none'
    CHECK (price_rounding IN ('none', '0.05', '0.10', '0.50', '1.00', '5.00', 'x.95', 'x.99'));
