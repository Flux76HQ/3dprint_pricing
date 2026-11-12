-- What a 3D model is offered for sale as: one listing per model, with the title and text of the advertisement, the price the owner asks
-- (typed, not derived: a new filament price must not change what an advertisement says) and, for a channel that wants one, an EAN.
CREATE TABLE listings (
    id           UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    project_id   UUID TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    price        NUM2 CHECK (price IS NULL OR price >= 0),         -- what the customer pays, VAT included; empty = not decided yet
    ean          TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE UNIQUE INDEX listings_project ON listings (project_id);
CREATE INDEX listings_updated ON listings (updated_at, id);

-- The photos of a listing, in the order they are shown. Each is a copy (an own upload, or one of the model's product pictures taken over),
-- so a listing keeps its photos when a product picture is made again or removed. They belong to the model and go with it.
CREATE TABLE listing_photos (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    project_id  UUID TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    content     BLOB NOT NULL,
    width_px    INTEGER NOT NULL,
    height_px   INTEGER NOT NULL,
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE INDEX listing_photos_project ON listing_photos (project_id, position);
