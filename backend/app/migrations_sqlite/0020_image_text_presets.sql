-- Standard texts for the fields of the product pictures (the setting, the product name, the short specs, the extra text): a text that is typed once, kept here, and
-- picked again in any calculation. They belong to the business, not to a calculation or to one person, so everybody who may make pictures sees the same list.
-- `field` is the field the text is for; `body` is the text as that field holds it (the specs are one per line). The same text is kept once per field.
CREATE TABLE image_text_presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    field       TEXT NOT NULL CHECK (field IN ('scene', 'product_name', 'specs', 'extra_text')),
    body        TEXT NOT NULL CHECK (length(body) > 0),
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE (field, body)
);
