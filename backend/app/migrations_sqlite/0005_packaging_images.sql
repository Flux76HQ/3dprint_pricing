-- A picture of a packaging item (the box or the bag as it is, or its logo): one per item, kept in the database like the other pictures
-- (a rebuilt container without its uploads folder must not lose it). It goes when the item goes.
CREATE TABLE packaging_images (
    packaging_id UUID TEXT PRIMARY KEY REFERENCES packaging_items(id) ON DELETE CASCADE,
    content      BLOB NOT NULL,
    sha256       TEXT NOT NULL,
    width_px     INTEGER NOT NULL,
    height_px    INTEGER NOT NULL,
    updated_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
