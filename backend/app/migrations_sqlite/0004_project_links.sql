-- A 3D model can have several links: where the model comes from, and where it is offered for sale (Marktplaats, Bol.com, a web shop...).
-- Each link names its kind, so that a later connection to such a channel has a place to keep the listing it made.
-- `source_url` stays: it keeps holding the link to the model itself, for a backup that is restored by an older release.
ALTER TABLE projects ADD COLUMN links JSON TEXT NOT NULL DEFAULT '[]';
UPDATE projects SET links = json_array(json_object('kind', 'model', 'label', '', 'url', source_url)) WHERE source_url <> '';
