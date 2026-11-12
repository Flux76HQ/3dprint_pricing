-- The pictures a calculation's images are made from are no longer one photo and one view per model: every photo that is uploaded
-- and every view of a 3D model that is saved is kept, next to the others. Which of them go to the image model is chosen per picture
-- (`selected`); what there was becomes: the first one of each calculation (its photo, else its oldest view).
DROP INDEX project_images_one_source;
ALTER TABLE project_images ADD COLUMN selected BOOLEAN NOT NULL DEFAULT 0;
UPDATE project_images SET selected = 1 WHERE id IN (
    SELECT id FROM (SELECT id, row_number() OVER (PARTITION BY project_id ORDER BY origin DESC, created_at, id) AS n
                    FROM project_images WHERE kind = 'source') WHERE n = 1);
