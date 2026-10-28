-- What happened the last time a notification went to each device, so Settings can say which devices
-- work and why one does not (instead of one vague error for all of them).
ALTER TABLE push_subscriptions
    ADD COLUMN last_ok_at    timestamptz,
    ADD COLUMN last_error    text,
    ADD COLUMN last_error_at timestamptz;
