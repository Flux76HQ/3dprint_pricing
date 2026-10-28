-- Restoring a backup runs in the background, so leaving the page (or closing the browser) does not stop it: one row for the restore
-- that is running or has just finished (the state a browser polls). It is not in a backup: it describes work in progress, not what the
-- owner entered, and a restore never touches it, so the row of the restore that is running survives its own swap.
CREATE TABLE backup_jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status        text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
    phase         text NOT NULL DEFAULT 'checking' CHECK (phase IN ('checking', 'replacing', 'done')),
    step          integer NOT NULL DEFAULT 0,
    steps         integer NOT NULL DEFAULT 0,
    error_key     text,
    error_params  jsonb NOT NULL DEFAULT '{}',
    summary       jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);
