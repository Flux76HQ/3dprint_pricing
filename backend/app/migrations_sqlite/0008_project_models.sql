-- A calculation keeps two kinds of print files apart. `file_id` stays the file the filament is worked out from (a sliced file gives
-- the exact grams and time). `models` is new: the 3D models of the object, one per part (the front and the back of a light box), each
-- {file_id, label}, to look at and to make pictures from.
ALTER TABLE projects ADD COLUMN models JSON TEXT NOT NULL DEFAULT '[]';
-- A saved view of a model says which model (and which build plate of it) it shows, as "<file id>" or "<file id>:<plate>"; a
-- calculation keeps one view per model and plate, next to its one photo. It is a name, not a link: the view stays when the file goes.
ALTER TABLE project_images ADD COLUMN model_ref TEXT NOT NULL DEFAULT '';
DROP INDEX project_images_one_source;
CREATE UNIQUE INDEX project_images_one_source ON project_images (project_id, origin, model_ref) WHERE kind = 'source';
