-- The uploaded file lives on disk (UPLOAD_DIR); the row holds what was read from it.
CREATE TABLE print_files (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename     text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('stl', '3mf')),
    size_bytes   bigint NOT NULL,
    sha256       text NOT NULL,
    stored_name  text NOT NULL UNIQUE,
    analysis     jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE projects ADD COLUMN file_id    uuid REFERENCES print_files(id) ON DELETE SET NULL;
ALTER TABLE projects ADD COLUMN source_url text NOT NULL DEFAULT '';
CREATE INDEX projects_file_id ON projects (file_id);
