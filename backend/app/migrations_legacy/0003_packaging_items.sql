-- Reusable packaging types (boxes, tape, bubble wrap...), priced per piece.
-- Calculations copy the price into their own lines, so editing a price here never
-- rewrites an old calculation.
CREATE TABLE packaging_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    price       numeric(12,2) NOT NULL CHECK (price >= 0),
    notes       text NOT NULL DEFAULT '',
    archived    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
