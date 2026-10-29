-- Limited user management (App-Guidance shared/guidelines/user-management.md). Until now there was one owner; now an
-- administrator can invite people, who sign in with their own passkey or password and work with the same data.
--
-- Two roles: `admin` (everything, including managing users) and `user` (everyday work, no management). The first person to set the app
-- up is the owner: an administrator who can never be removed, reset or demoted, so the installation always has one. Any
-- other user can be promoted to administrator by an administrator.
ALTER TABLE users
    ADD COLUMN role           text    NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    ADD COLUMN is_owner       boolean NOT NULL DEFAULT false,
    -- Put in the session, compared on every request: a reset bumps it, which signs that one person out everywhere.
    ADD COLUMN session_epoch  integer NOT NULL DEFAULT 0,
    ADD CONSTRAINT users_owner_is_admin CHECK (NOT is_owner OR role = 'admin');

UPDATE users SET role = 'admin';
UPDATE users SET is_owner = true WHERE id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1);
CREATE UNIQUE INDEX users_one_owner ON users (is_owner) WHERE is_owner;
-- The name is also what a person types to sign in with a password, so it is unique regardless of case.
CREATE UNIQUE INDEX users_name_unique ON users (lower(display_name));

-- An invitation: a link the guest opens to choose their own password or passkey (`kind` new), or to get back in after losing
-- both (`kind` reset). Only the SHA-256 of the token is kept; the link is shown once, when it is made. Using it deletes it.
-- The two `pending_*` columns hold a password-and-authenticator setup that is not finished yet, so that nothing is created (and
-- nothing of a reset user's old sign-in is touched) until the guest has confirmed the code.
CREATE TABLE invitations (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash             bytea NOT NULL UNIQUE,
    kind                   text NOT NULL CHECK (kind IN ('new', 'reset')),
    user_id                uuid REFERENCES users(id) ON DELETE CASCADE,       -- reset only: the person who gets back in
    display_name           text NOT NULL DEFAULT '',                          -- new: the name suggested (and reserved); reset: theirs
    created_by             uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    expires_at             timestamptz NOT NULL,
    pending_name           text,
    pending_password_hash  text,
    pending_totp_secret    bytea,
    CHECK ((kind = 'reset') = (user_id IS NOT NULL))
);
-- At most one reset link per person; a new one replaces the old.
CREATE UNIQUE INDEX invitations_one_reset ON invitations (user_id) WHERE kind = 'reset';

ALTER TABLE webauthn_challenges DROP CONSTRAINT webauthn_challenges_kind_check;
ALTER TABLE webauthn_challenges ADD CONSTRAINT webauthn_challenges_kind_check
    CHECK (kind IN ('onboarding', 'register', 'login', 'confirm', 'invite'));

-- What belongs to the business and not to a person: the company details on an invoice, the VAT rate and rounding that new orders
-- start from, and the low-stock thresholds. These used to live in the owner's own preferences; with more than one person that
-- would give everybody else an empty company. One row (`id` can only be true).
CREATE TABLE shared_preferences (
    id           boolean PRIMARY KEY DEFAULT true CHECK (id),
    preferences  jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now()
);
INSERT INTO shared_preferences (preferences)
SELECT COALESCE((SELECT jsonb_object_agg(key, value) FROM jsonb_each(u.preferences)
                  WHERE key IN ('business', 'vat_pct', 'price_rounding', 'low_stock')), '{}'::jsonb)
FROM (SELECT preferences FROM users ORDER BY created_at, id LIMIT 1) u;
UPDATE users SET preferences = preferences - 'business' - 'vat_pct' - 'price_rounding' - 'low_stock';
