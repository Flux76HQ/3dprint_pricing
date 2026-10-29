-- Web push: one row per browser/device that opted in, a queue for notifications held back by quiet
-- hours (deferred, never discarded), and a little key/value state for the release announcement.
CREATE TABLE push_subscriptions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    text NOT NULL UNIQUE,
    p256dh      text NOT NULL,
    auth        text NOT NULL,
    user_agent  text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- At most one waiting notification per user and kind: only the newest survives, like an RFC 8030 topic.
CREATE TABLE push_outbox (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind           text NOT NULL,
    payload        jsonb NOT NULL,
    deliver_after  timestamptz NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, kind)
);

CREATE TABLE app_state (
    key    text PRIMARY KEY,
    value  text NOT NULL
);
