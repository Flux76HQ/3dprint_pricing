-- Connections with other applications (a finance app, later a sales channel).
--
-- An API key lets another application read orders, invoices and customers (the read-only API under /api/v1) without a browser session. Only its
-- SHA-256 is kept: the key itself is shown once, when it is made. It is nobody's session and stays when the person who made it leaves.
CREATE TABLE api_keys (
    id            UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name          TEXT NOT NULL,
    shown         TEXT NOT NULL,                                  -- the first characters of the key, to tell keys apart; not enough to use it
    key_hash      TEXT NOT NULL,
    created_by    UUID TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    last_used_at  TIMESTAMP TEXT
);
CREATE UNIQUE INDEX api_keys_hash ON api_keys (key_hash);

-- An address that is told when something happens (an invoice is made, an order changes). The key its messages are signed with has to be
-- readable to sign, so it is sealed (passwords.seal), never returned after it was shown once.
CREATE TABLE webhook_endpoints (
    id               UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name             TEXT NOT NULL,
    url              TEXT NOT NULL,
    events           JSON TEXT NOT NULL,
    signing_key_enc  TEXT NOT NULL,
    enabled          BOOLEAN NOT NULL DEFAULT 1,
    disabled_reason  TEXT NOT NULL DEFAULT '',                    -- why it was switched off without anyone asking: 'failing' or 'gone'
    failing_since    TIMESTAMP TEXT,                              -- the first failure since the last message that arrived
    created_by       UUID TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

-- The messages: the outbox and the delivery log in one. A row is written in the transaction of what it reports, so the two are kept or lost
-- together. `body` is the message as it is sent, serialised once: a retry signs and sends the same bytes.
CREATE TABLE webhook_deliveries (
    id               UUID TEXT PRIMARY KEY,
    endpoint_id      UUID TEXT NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
    event            TEXT NOT NULL,
    body             TEXT NOT NULL,
    state            TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'delivered', 'dead')),
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMP TEXT,                              -- when it is tried (again); empty once it arrived or was given up
    last_status      INTEGER,                                     -- the HTTP status of the last attempt, when there was an answer
    last_error       TEXT NOT NULL DEFAULT '',                    -- why the last attempt failed, as a message key
    created_at       TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    delivered_at     TIMESTAMP TEXT
);
CREATE INDEX webhook_deliveries_due ON webhook_deliveries (next_attempt_at) WHERE state = 'pending';
CREATE INDEX webhook_deliveries_endpoint ON webhook_deliveries (endpoint_id, created_at);
