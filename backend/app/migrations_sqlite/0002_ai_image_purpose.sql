-- AI product images are made for a purpose (a marketplace ad, social media, a web shop), four per purpose, and may carry the
-- product texts and the logo in a fixed template. What was chosen and typed is kept with the calculation (`image_text`), each
-- queued picture keeps what it is to be made with, and a picture remembers what it was made for.
ALTER TABLE projects ADD COLUMN image_text JSON TEXT NOT NULL DEFAULT '{}';
ALTER TABLE project_images ADD COLUMN purpose TEXT;
ALTER TABLE ai_image_jobs ADD COLUMN purpose TEXT;
ALTER TABLE ai_image_jobs ADD COLUMN overlay JSON TEXT NOT NULL DEFAULT '{}';
