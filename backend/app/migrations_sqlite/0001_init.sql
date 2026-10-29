-- 3D Print Pricing, SQLite schema (the baseline: the end state of the 27 PostgreSQL migrations in migrations_legacy/).
--
-- Declared types are read by app/db.py: UUID TEXT, TIMESTAMP TEXT (UTC), JSON TEXT, DATE TEXT, BOOLEAN, and NUM1..NUM4
-- (a decimal with that many digits behind the point; NUMERIC affinity so CHECKs and comparisons stay numeric).
-- Ids and timestamps get their defaults here so an INSERT without them works from any client.

-- The next project and order number (named 'project' and 'order'): numbers are never reused, also not after a delete.
CREATE TABLE counters (
    name  TEXT PRIMARY KEY,
    last  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE users (
    id             UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    display_name   TEXT NOT NULL,
    preferences    JSON TEXT NOT NULL DEFAULT '{}',
    created_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    role           TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_owner       BOOLEAN NOT NULL DEFAULT 0,
    session_epoch  INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT users_owner_is_admin CHECK (NOT is_owner OR role = 'admin')
);
CREATE UNIQUE INDEX users_one_owner ON users (is_owner) WHERE is_owner;
CREATE UNIQUE INDEX users_name_unique ON users (lower_u(display_name));

CREATE TABLE webauthn_credentials (
    id             UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    user_id        UUID TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id  BLOB NOT NULL UNIQUE,
    public_key     BLOB NOT NULL,
    sign_count     INTEGER NOT NULL DEFAULT 0,
    transports     JSON TEXT NOT NULL DEFAULT '[]',
    label          TEXT NOT NULL DEFAULT 'Passkey',
    created_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    last_used_at   TIMESTAMP TEXT
);

CREATE TABLE recovery_codes (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    user_id     UUID TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    salt        BLOB NOT NULL,
    code_hash   BLOB NOT NULL,
    used_at     TIMESTAMP TEXT,
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE webauthn_challenges (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    challenge   BLOB NOT NULL UNIQUE,
    kind        TEXT NOT NULL CHECK (kind IN ('onboarding', 'register', 'login', 'confirm', 'invite')),
    purpose     TEXT,
    user_id     UUID TEXT REFERENCES users(id) ON DELETE CASCADE,
    data        JSON TEXT NOT NULL DEFAULT '{}',
    expires_at  TIMESTAMP TEXT NOT NULL
);

CREATE TABLE password_credentials (
    user_id              UUID TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash        TEXT NOT NULL,
    totp_secret          BLOB,
    enabled              BOOLEAN NOT NULL DEFAULT 1,
    last_totp_step       INTEGER NOT NULL DEFAULT 0,
    failed_count         INTEGER NOT NULL DEFAULT 0,
    locked_until         TIMESTAMP TEXT,
    created_at           TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at           TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    pending_totp_secret  BLOB
);

CREATE TABLE mfa_backup_codes (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    user_id     UUID TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    salt        BLOB NOT NULL,
    code_hash   BLOB NOT NULL,
    used_at     TIMESTAMP TEXT,
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE invitations (
    id            UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    token_hash    BLOB NOT NULL UNIQUE,
    kind          TEXT NOT NULL CHECK (kind IN ('new', 'reset')),
    user_id       UUID TEXT REFERENCES users(id) ON DELETE CASCADE,
    display_name  TEXT NOT NULL DEFAULT '',
    created_by    UUID TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    expires_at    TIMESTAMP TEXT NOT NULL,
    CHECK ((kind = 'reset') = (user_id IS NOT NULL))
);
CREATE UNIQUE INDEX invitations_one_reset ON invitations (user_id) WHERE kind = 'reset';

CREATE TABLE shared_preferences (
    id           BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (id),
    preferences  JSON TEXT NOT NULL DEFAULT '{}',
    updated_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE printers (
    id              UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name            TEXT NOT NULL,
    purchase_price  NUM2 NOT NULL CHECK (purchase_price >= 0),
    lifetime_hours  NUM1 NOT NULL CHECK (lifetime_hours > 0),
    power_kw        NUM3 NOT NULL DEFAULT 0 CHECK (power_kw >= 0),
    notes           TEXT NOT NULL DEFAULT '',
    archived        BOOLEAN NOT NULL DEFAULT 0,
    created_at      TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE energy_tariffs (
    id             UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name           TEXT NOT NULL,
    price_per_kwh  NUM4 NOT NULL CHECK (price_per_kwh >= 0),
    is_default     BOOLEAN NOT NULL DEFAULT 0,
    created_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE UNIQUE INDEX energy_tariffs_one_default ON energy_tariffs (is_default) WHERE is_default;

CREATE TABLE filament_spools (
    id                  UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    brand               TEXT NOT NULL,
    material            TEXT NOT NULL DEFAULT '',
    colour              TEXT NOT NULL DEFAULT '',
    roll_weight_g       NUM1 NOT NULL CHECK (roll_weight_g > 0),
    price               NUM2 NOT NULL CHECK (price >= 0),
    remaining_g         NUM1 NOT NULL CHECK (remaining_g >= 0),
    notes               TEXT NOT NULL DEFAULT '',
    archived            BOOLEAN NOT NULL DEFAULT 0,
    created_at          TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    barcode             TEXT NOT NULL DEFAULT '',
    diameter_mm         NUM2 NOT NULL DEFAULT 1.75 CHECK (diameter_mm > 0 AND diameter_mm <= 5),
    print_temp_c        INTEGER CHECK (print_temp_c BETWEEN 0 AND 500),
    bed_temp_c          INTEGER CHECK (bed_temp_c BETWEEN 0 AND 200),
    product_type        TEXT NOT NULL DEFAULT '',
    notify_low          BOOLEAN NOT NULL DEFAULT 0,
    colour_hex          TEXT NOT NULL DEFAULT '' CHECK (colour_hex = '' OR colour_hex GLOB '#[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
    spoolman_id         INTEGER,
    spoolman_synced_at  TIMESTAMP TEXT
);
CREATE INDEX filament_spools_barcode ON filament_spools (barcode) WHERE barcode <> '';
CREATE UNIQUE INDEX filament_spools_spoolman_id ON filament_spools (spoolman_id) WHERE spoolman_id IS NOT NULL;

CREATE TABLE packaging_items (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name        TEXT NOT NULL,
    price       NUM2 NOT NULL CHECK (price >= 0),
    notes       TEXT NOT NULL DEFAULT '',
    archived    BOOLEAN NOT NULL DEFAULT 0,
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE part_items (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name        TEXT NOT NULL,
    price       NUM2 NOT NULL CHECK (price >= 0),
    unit        TEXT NOT NULL DEFAULT 'stuks' CHECK (unit IN ('stuks', 'm', 'g')),
    notes       TEXT NOT NULL DEFAULT '',
    archived    BOOLEAN NOT NULL DEFAULT 0,
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE accessory_items (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name        TEXT NOT NULL,
    price       NUM2 NOT NULL CHECK (price >= 0),
    unit        TEXT NOT NULL DEFAULT 'stuks' CHECK (unit IN ('stuks', 'm', 'g')),
    notes       TEXT NOT NULL DEFAULT '',
    archived    BOOLEAN NOT NULL DEFAULT 0,
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE filament_library (
    id             UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    brand          TEXT NOT NULL,
    product_type   TEXT NOT NULL DEFAULT '',
    material       TEXT NOT NULL DEFAULT '',
    colour         TEXT NOT NULL DEFAULT '',
    colour_hex     TEXT NOT NULL DEFAULT '' CHECK (colour_hex = '' OR colour_hex GLOB '#[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
    filament_id    TEXT NOT NULL DEFAULT '',
    sku            TEXT NOT NULL DEFAULT '',
    barcode        TEXT NOT NULL DEFAULT '',
    refill         BOOLEAN NOT NULL DEFAULT 0,
    roll_weight_g  NUM1 NOT NULL DEFAULT 1000 CHECK (roll_weight_g > 0),
    diameter_mm    NUM2 NOT NULL DEFAULT 1.75 CHECK (diameter_mm > 0),
    print_temp_c   INTEGER CHECK (print_temp_c BETWEEN 0 AND 500),
    bed_temp_c     INTEGER CHECK (bed_temp_c BETWEEN 0 AND 200),
    price          NUM2 CHECK (price >= 0),
    notes          TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE INDEX filament_library_sku ON filament_library (lower_u(brand), lower_u(sku)) WHERE sku <> '';

CREATE TABLE print_files (
    id           UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    filename     TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('stl', '3mf')),
    size_bytes   INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    stored_name  TEXT NOT NULL UNIQUE,
    analysis     JSON TEXT NOT NULL,
    created_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE projects (
    id                 UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    name               TEXT NOT NULL,
    notes              TEXT NOT NULL DEFAULT '',
    margin_pct         NUM2 NOT NULL DEFAULT 0 CHECK (margin_pct >= 0),
    data               JSON TEXT NOT NULL,
    totals             JSON TEXT NOT NULL,
    stock_booked_at    TIMESTAMP TEXT,
    created_at         TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at         TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    file_id            UUID TEXT REFERENCES print_files(id) ON DELETE SET NULL,
    source_url         TEXT NOT NULL DEFAULT '',
    vat_pct            NUM2 NOT NULL DEFAULT 0 CHECK (vat_pct >= 0 AND vat_pct <= 100),
    price_rounding     TEXT NOT NULL DEFAULT 'none' CHECK (price_rounding IN ('none', '0.05', '0.10', '0.50', '1.00', '5.00', 'x.95', 'x.99')),
    number             INTEGER NOT NULL,
    object_description TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX projects_number_key ON projects (number);
CREATE INDEX projects_file_id ON projects (file_id);

CREATE TABLE project_images (
    id          UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    project_id  UUID TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('source', 'generated')),
    variant     TEXT,
    mime        TEXT NOT NULL,
    content     BLOB NOT NULL,
    width_px    INTEGER NOT NULL,
    height_px   INTEGER NOT NULL,
    is_cover    BOOLEAN NOT NULL DEFAULT 0,
    created_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE INDEX project_images_project ON project_images (project_id, created_at);
CREATE UNIQUE INDEX project_images_one_source ON project_images (project_id) WHERE kind = 'source';
CREATE UNIQUE INDEX project_images_one_cover ON project_images (project_id) WHERE is_cover;

CREATE TABLE customers (
    id           UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    number       TEXT NOT NULL,
    name         TEXT NOT NULL,
    address      TEXT NOT NULL DEFAULT '',
    postal_code  TEXT NOT NULL DEFAULT '',
    city         TEXT NOT NULL DEFAULT '',
    country      TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    phone        TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);
CREATE UNIQUE INDEX customers_number_key ON customers (lower_u(number));
CREATE INDEX customers_name_idx ON customers (lower_u(name));

CREATE TABLE orders (
    id              UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    number          INTEGER NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'nieuw' CHECK (status IN ('nieuw', 'verwerkt', 'verstuurd', 'afgehandeld')),
    order_date      DATE TEXT NOT NULL DEFAULT (date('now')),
    delivery_date   DATE TEXT,
    customer_name   TEXT NOT NULL,
    address         TEXT NOT NULL DEFAULT '',
    postal_code     TEXT NOT NULL DEFAULT '',
    city            TEXT NOT NULL DEFAULT '',
    country         TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    invoice_number  TEXT UNIQUE,
    invoice_date    DATE TEXT,
    created_at      TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at      TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    customer_number TEXT NOT NULL DEFAULT '',
    subject         TEXT NOT NULL DEFAULT '',
    customer_id     UUID TEXT NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    price_rounding  TEXT NOT NULL DEFAULT 'none' CHECK (price_rounding IN ('none', '0.05', '0.10', '0.50', '1.00', '5.00', 'x.95', 'x.99'))
);
CREATE INDEX orders_order_date_idx ON orders (order_date DESC);
CREATE INDEX orders_customer_idx ON orders (customer_id);

CREATE TABLE order_lines (
    id              UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    order_id        UUID TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    project_id      UUID TEXT REFERENCES projects(id) ON DELETE SET NULL,
    project_number  INTEGER,
    description     TEXT NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity >= 1),
    unit_price      NUM2 NOT NULL CHECK (unit_price >= 0),
    vat_pct         NUM2 NOT NULL DEFAULT 0 CHECK (vat_pct >= 0 AND vat_pct <= 100),
    cost_price      NUM2 CHECK (cost_price >= 0),
    margin_pct      NUM2 CHECK (margin_pct >= 0),
    optional        BOOLEAN NOT NULL DEFAULT 0
);
CREATE INDEX order_lines_order_idx ON order_lines (order_id, position);

CREATE TABLE invoice_counters (
    year  INTEGER PRIMARY KEY,
    last  INTEGER NOT NULL
);

CREATE TABLE invoice_template (
    id                BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (id),
    filename          TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('docx', 'pdf')),
    stored_name       TEXT,
    size_bytes        INTEGER NOT NULL,
    sha256            TEXT NOT NULL,
    margin_top_mm     INTEGER NOT NULL DEFAULT 55 CHECK (margin_top_mm BETWEEN 0 AND 200),
    margin_bottom_mm  INTEGER NOT NULL DEFAULT 25 CHECK (margin_bottom_mm BETWEEN 0 AND 200),
    uploaded_at       TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    content           BLOB
);

CREATE TABLE invoice_logo (
    id           BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (id),
    filename     TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('png', 'jpeg')),
    stored_name  TEXT,
    size_bytes   INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    width_px     INTEGER NOT NULL,
    height_px    INTEGER NOT NULL,
    uploaded_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    content      BLOB
);

CREATE TABLE invoice_pdfs (
    order_id        UUID TEXT PRIMARY KEY REFERENCES orders (id) ON DELETE CASCADE,
    invoice_number  TEXT NOT NULL,
    content         BLOB NOT NULL,
    size_bytes      INTEGER NOT NULL,
    created_at      TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE ai_image_settings (
    id           BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (id),
    api_key_enc  TEXT,
    model        TEXT NOT NULL DEFAULT 'gpt-image-2',
    quality      TEXT NOT NULL DEFAULT 'medium' CHECK (quality IN ('low', 'medium', 'high')),
    updated_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now'))
);

CREATE TABLE ai_image_jobs (
    id            UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    project_id    UUID TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    batch_id      UUID TEXT NOT NULL,
    position      INTEGER NOT NULL,
    variant       TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    error_key     TEXT,
    error_params  JSON TEXT NOT NULL DEFAULT '{}',
    detail        TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at    TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    finished_at   TIMESTAMP TEXT
);
CREATE INDEX ai_image_jobs_project ON ai_image_jobs (project_id, created_at);

CREATE TABLE ai_image_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    level           TEXT NOT NULL CHECK (level IN ('info', 'error')),
    message_key     TEXT NOT NULL,
    message_params  JSON TEXT NOT NULL DEFAULT '{}',
    detail          TEXT NOT NULL DEFAULT '',
    project_id      UUID TEXT REFERENCES projects (id) ON DELETE SET NULL,
    project_number  INTEGER,
    project_name    TEXT,
    variant         TEXT
);
CREATE INDEX ai_image_log_created ON ai_image_log (created_at DESC, id DESC);

CREATE TABLE push_subscriptions (
    id             UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    user_id        UUID TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint       TEXT NOT NULL UNIQUE,
    p256dh         TEXT NOT NULL,
    auth           TEXT NOT NULL,
    user_agent     TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    last_ok_at     TIMESTAMP TEXT,
    last_error     TEXT,
    last_error_at  TIMESTAMP TEXT
);

CREATE TABLE push_outbox (
    id             UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    user_id        UUID TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL,
    payload        JSON TEXT NOT NULL,
    deliver_after  TIMESTAMP TEXT NOT NULL,
    created_at     TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    UNIQUE (user_id, kind)
);

CREATE TABLE low_stock_alerts (
    user_id      UUID TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stock_key    TEXT NOT NULL,
    notified_at  TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY (user_id, stock_key)
);

CREATE TABLE app_state (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE backup_jobs (
    id                 UUID TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
    status             TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
    phase              TEXT NOT NULL DEFAULT 'checking' CHECK (phase IN ('checking', 'replacing', 'done')),
    step               INTEGER NOT NULL DEFAULT 0,
    steps              INTEGER NOT NULL DEFAULT 0,
    error_key          TEXT,
    error_params       JSON TEXT NOT NULL DEFAULT '{}',
    summary            JSON TEXT NOT NULL DEFAULT '{}',
    created_at         TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_at         TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    finished_at        TIMESTAMP TEXT,
    checking_seconds   REAL,
    replacing_seconds  REAL
);

CREATE TABLE spoolman_pending_use (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    spoolman_id  INTEGER NOT NULL,
    grams        NUM1 NOT NULL CHECK (grams > 0),
    created_at   TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    claimed_until TIMESTAMP TEXT       -- a flush that is sending this one leaves it alone until then (a crash hands it back)
);

CREATE TABLE spoolman_settings (
    singleton  BOOLEAN PRIMARY KEY DEFAULT 1 CHECK (singleton),
    url        TEXT NOT NULL DEFAULT ''
);
