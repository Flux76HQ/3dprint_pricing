-- Every view that is saved of a 3D model is kept: turning the model and saving again adds a picture, it no longer replaces the one
-- that was there. A calculation still has one photo of the object.
DROP INDEX project_images_one_source;
CREATE UNIQUE INDEX project_images_one_source ON project_images (project_id) WHERE kind = 'source' AND origin = 'photo';
