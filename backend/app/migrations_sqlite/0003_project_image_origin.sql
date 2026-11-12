-- A calculation can have two pictures to make its images from: a photo of the printed object, and a picture of its 3D model as
-- it was turned in the viewer. Both are `kind = 'source'`; `origin` says which one, and there is at most one of each.
ALTER TABLE project_images ADD COLUMN origin TEXT NOT NULL DEFAULT 'photo' CHECK (origin IN ('photo', 'model'));
DROP INDEX project_images_one_source;
CREATE UNIQUE INDEX project_images_one_source ON project_images (project_id, origin) WHERE kind = 'source';
