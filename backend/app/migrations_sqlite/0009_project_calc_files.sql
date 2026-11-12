-- The filament of a calculation can be worked out from several files: an object that is printed as more than one job (the front
-- and the back of a light box, each sliced on its own) has a sliced file per job. `calc_files` is the list of their ids, in order;
-- `file_id` stays and is the first of them, for a backup that is restored by an older release.
ALTER TABLE projects ADD COLUMN calc_files JSON TEXT NOT NULL DEFAULT '[]';
UPDATE projects SET calc_files = json_array(file_id) WHERE file_id IS NOT NULL;
