-- AI product images are made in the background, so leaving the page does not stop them: one row per picture to make (the state a
-- browser polls), and a log of what happened (also for what went wrong), shown under Settings -> AI images. Neither is in a backup:
-- they describe work in progress and history, not what the owner entered.
CREATE TABLE ai_image_jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    batch_id      uuid NOT NULL,
    position      integer NOT NULL,
    variant       text NOT NULL,
    description   text NOT NULL DEFAULT '',
    status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    error_key     text,
    error_params  jsonb NOT NULL DEFAULT '{}',
    detail        text NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);
CREATE INDEX ai_image_jobs_project ON ai_image_jobs (project_id, created_at);

CREATE TABLE ai_image_log (
    id              bigserial PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    level           text NOT NULL CHECK (level IN ('info', 'error')),
    message_key     text NOT NULL,
    message_params  jsonb NOT NULL DEFAULT '{}',
    detail          text NOT NULL DEFAULT '',
    project_id      uuid REFERENCES projects (id) ON DELETE SET NULL,
    project_number  integer,
    project_name    text,
    variant         text
);
CREATE INDEX ai_image_log_created ON ai_image_log (created_at DESC, id DESC);
