-- Optional AI product images (only reachable when AI_IMAGES_ENABLED=TRUE in .env): a free-text description of the object (used to
-- choose a fitting background), the OpenAI key and model (the key is encrypted with a key derived from SESSION_SECRET), and the
-- photos per calculation. Images are kept in the database like the invoice logo, so a rebuilt container without its volume loses none.
ALTER TABLE projects ADD COLUMN object_description text NOT NULL DEFAULT '';

CREATE TABLE ai_image_settings (
    id           boolean PRIMARY KEY DEFAULT true CHECK (id),
    api_key_enc  text,
    model        text NOT NULL DEFAULT 'gpt-image-2',
    quality      text NOT NULL DEFAULT 'medium' CHECK (quality IN ('low', 'medium', 'high')),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_images (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('source', 'generated')),
    variant     text,
    mime        text NOT NULL,
    content     bytea NOT NULL,
    width_px    integer NOT NULL,
    height_px   integer NOT NULL,
    is_cover    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX project_images_project ON project_images (project_id, created_at);
-- one source photo per calculation, one cover per calculation
CREATE UNIQUE INDEX project_images_one_source ON project_images (project_id) WHERE kind = 'source';
CREATE UNIQUE INDEX project_images_one_cover ON project_images (project_id) WHERE is_cover;
