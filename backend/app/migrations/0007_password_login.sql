-- Optional password login. It exists only together with a confirmed second factor (TOTP): a row is
-- written as `enabled = false` during setup and flips to true when the first code is confirmed.
CREATE TABLE password_credentials (
    user_id         uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash   text NOT NULL,                       -- argon2id
    totp_secret     bytea NOT NULL,                      -- Fernet token: encrypted at rest, never plaintext
    enabled         boolean NOT NULL DEFAULT false,
    last_totp_step  bigint NOT NULL DEFAULT 0,           -- a code is only good once
    failed_count    integer NOT NULL DEFAULT 0,          -- password and code failures, reset by a full login
    locked_until    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mfa_backup_codes (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    salt        bytea NOT NULL,
    code_hash   bytea NOT NULL,                          -- sha256(salt || normalised code)
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
