-- Notification when a kind of filament is nearly used up. `notify_low` is chosen per roll, but belongs to the kind: rolls with
-- the same barcode (or, without one, the same brand, type, material and colour) are given the same value and count together.
ALTER TABLE filament_spools ADD COLUMN notify_low boolean NOT NULL DEFAULT false;

-- Which kinds the owner has already been told are nearly used up. A row exists while a kind is at or below its threshold and is
-- removed when the stock recovers (or the notification is switched off for it), so a notification follows each drop below the
-- threshold, not each change to a roll that is already low. `stock_key` is the kind's key (see app/stock.py).
CREATE TABLE low_stock_alerts (
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_key    text NOT NULL,
    notified_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, stock_key)
);
