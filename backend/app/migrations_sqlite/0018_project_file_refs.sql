-- Where the files of a 3D model are kept outside this app: a link to a cloud drive (iCloud Drive, Google Drive, OneDrive, Dropbox) or the path of a folder on a
-- network share (a NAS). Each place names its kind, so the screen can say what it is and offer the right way to open it. They are only remembered here, never opened or read.
ALTER TABLE projects ADD COLUMN file_refs JSON TEXT NOT NULL DEFAULT '[]';
