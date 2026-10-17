-- Which materials the owner has already been told are nearly used up. A row exists while a material is at or below
-- its threshold and is removed when the stock recovers, so a notification follows each drop below the threshold,
-- not each change to a roll that is already low.
CREATE TABLE low_stock_alerts (
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    material     text NOT NULL,
    notified_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, material)
);
