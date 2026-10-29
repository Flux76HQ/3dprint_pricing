-- Reusable parts (cables, connectors, chips...) and accessories (cables, chargers...), priced per piece,
-- per metre or per kg. Like packaging, a calculation copies the price into its own line, so editing a
-- price here never rewrites an old calculation.
CREATE TABLE part_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    price       numeric(12,2) NOT NULL CHECK (price >= 0),
    unit        text NOT NULL DEFAULT 'stuks' CHECK (unit IN ('stuks', 'm', 'g')),
    notes       text NOT NULL DEFAULT '',
    archived    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE accessory_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    price       numeric(12,2) NOT NULL CHECK (price >= 0),
    unit        text NOT NULL DEFAULT 'stuks' CHECK (unit IN ('stuks', 'm', 'g')),
    notes       text NOT NULL DEFAULT '',
    archived    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
