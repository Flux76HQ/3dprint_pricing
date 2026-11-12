-- What a set of AI pictures cost: the tokens OpenAI counted for each picture (`usage` in its answer), and what they came to.
--
-- Prices are OpenAI's, in US dollars per million tokens (text in, image in, image out), and the rate turns dollars into euros. All four are
-- typed by an administrator (NULL = not typed: the app then knows OpenAI's own list price for the model it was made with, if it knows that model,
-- and no rate at all). They are kept as they were *with every picture* (below), so changing a price later does not rewrite what was spent.
ALTER TABLE ai_image_settings ADD COLUMN price_text_in NUM4;
ALTER TABLE ai_image_settings ADD COLUMN price_image_in NUM4;
ALTER TABLE ai_image_settings ADD COLUMN price_image_out NUM4;
ALTER TABLE ai_image_settings ADD COLUMN usd_eur NUM4;

-- One row per picture that was made, written in the transaction that stores the picture. A set is what one request made (`batch_id`). A row stays when
-- the calculation goes (the money is spent): the number and the name are copied, as in the log. `reported` is false when OpenAI's answer did not say how
-- many tokens (then none are guessed and there is no cost). A price or a rate that was not known then is NULL here; for a rate the current one is used.
CREATE TABLE ai_image_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TIMESTAMP TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    batch_id            UUID TEXT NOT NULL,
    project_id          UUID TEXT REFERENCES projects (id) ON DELETE SET NULL,
    project_number      INTEGER,
    project_name        TEXT,
    purpose             TEXT,
    variant             TEXT NOT NULL,
    model               TEXT NOT NULL,
    quality             TEXT NOT NULL,
    reported            BOOLEAN NOT NULL DEFAULT 1,
    input_text_tokens   INTEGER NOT NULL DEFAULT 0 CHECK (input_text_tokens >= 0),
    input_image_tokens  INTEGER NOT NULL DEFAULT 0 CHECK (input_image_tokens >= 0),
    output_tokens       INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    price_text_in       NUM4,
    price_image_in      NUM4,
    price_image_out     NUM4,
    usd_eur             NUM4
);
CREATE INDEX ai_image_usage_created ON ai_image_usage (created_at DESC, id DESC);
