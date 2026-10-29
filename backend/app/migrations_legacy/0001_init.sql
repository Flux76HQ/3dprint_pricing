CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Identity ------------------------------------------------------------------
CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name  text NOT NULL,
    preferences   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE webauthn_credentials (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id  bytea NOT NULL UNIQUE,
    public_key     bytea NOT NULL,            -- COSE_Key, ES256 only
    sign_count     bigint NOT NULL DEFAULT 0,
    transports     jsonb NOT NULL DEFAULT '[]'::jsonb,
    label          text NOT NULL DEFAULT 'Passkey',
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_used_at   timestamptz
);

CREATE TABLE recovery_codes (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    salt        bytea NOT NULL,
    code_hash   bytea NOT NULL,               -- sha256(salt || normalised code)
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Short-lived, single-use. `purpose` binds a step-up confirmation to the
-- action it confirms; `data` carries onboarding state between the two calls.
CREATE TABLE webauthn_challenges (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge   bytea NOT NULL UNIQUE,
    kind        text NOT NULL CHECK (kind IN ('onboarding', 'register', 'login', 'confirm')),
    purpose     text,
    user_id     uuid REFERENCES users(id) ON DELETE CASCADE,
    data        jsonb NOT NULL DEFAULT '{}'::jsonb,
    expires_at  timestamptz NOT NULL
);

-- Inventory & rates ---------------------------------------------------------
CREATE TABLE printers (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    purchase_price  numeric(12,2) NOT NULL CHECK (purchase_price >= 0),
    lifetime_hours  numeric(10,1) NOT NULL CHECK (lifetime_hours > 0),
    power_kw        numeric(8,3)  NOT NULL DEFAULT 0 CHECK (power_kw >= 0),
    notes           text NOT NULL DEFAULT '',
    archived        boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE energy_tariffs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name           text NOT NULL,
    price_per_kwh  numeric(10,4) NOT NULL CHECK (price_per_kwh >= 0),
    is_default     boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX energy_tariffs_one_default ON energy_tariffs (is_default) WHERE is_default;

CREATE TABLE filament_spools (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand          text NOT NULL,
    material       text NOT NULL DEFAULT '',
    colour         text NOT NULL DEFAULT '',
    roll_weight_g  numeric(10,1) NOT NULL CHECK (roll_weight_g > 0),
    price          numeric(12,2) NOT NULL CHECK (price >= 0),
    remaining_g    numeric(10,1) NOT NULL CHECK (remaining_g >= 0),
    notes          text NOT NULL DEFAULT '',
    archived       boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Calculations --------------------------------------------------------------
-- `data` holds the input lines with the prices as they were when saved, so a
-- later price change never rewrites an old calculation; `totals` is the
-- calculator's output for that data.
CREATE TABLE projects (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL,
    notes            text NOT NULL DEFAULT '',
    margin_pct       numeric(6,2) NOT NULL DEFAULT 0 CHECK (margin_pct >= 0),
    data             jsonb NOT NULL,
    totals           jsonb NOT NULL,
    stock_booked_at  timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
