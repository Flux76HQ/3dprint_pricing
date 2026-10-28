-- A password login no longer needs an authenticator app: the app can be set up on an address where no passkey works
-- (an IP address on a home network) with a password alone, and two-step verification is something a person adds.
--
-- A `password_credentials` row now means "this person can sign in with a password" (`enabled`). `totp_secret` is NULL while
-- they have no authenticator app and the encrypted secret once they have confirmed one; a secret still being set up waits in
-- `pending_totp_secret` so the confirmed one keeps working until the new one is confirmed.

-- Half-finished set-ups of the old flow (a password waiting for its first code) never grant anything; they go.
DELETE FROM password_credentials WHERE NOT enabled;

ALTER TABLE password_credentials ALTER COLUMN totp_secret DROP NOT NULL;
ALTER TABLE password_credentials ALTER COLUMN enabled SET DEFAULT true;
ALTER TABLE password_credentials ADD COLUMN pending_totp_secret bytea;       -- Fernet token, like totp_secret

-- An invitation kept a password-and-authenticator set-up that was not finished; the password is now set in one step.
ALTER TABLE invitations DROP COLUMN pending_name, DROP COLUMN pending_password_hash, DROP COLUMN pending_totp_secret;
