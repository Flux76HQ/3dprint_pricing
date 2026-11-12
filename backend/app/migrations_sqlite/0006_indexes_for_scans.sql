-- Indexes for the statements that read a whole table to find a few rows. They were found by explaining every statement the test suite
-- sends on a database of 300 models, 600 orders and 200 rolls (docs/performance.md); tests/test_query_plans.py asserts that the code's
-- own statements use them.

-- A scanned roll is looked up by its barcode, newest first. The index that was there covered only rolls with a barcode
-- (WHERE barcode <> ''), and SQLite cannot use such an index for `barcode = ?`: it does not know that the value asked for is not ''.
-- So every scan read every roll.
DROP INDEX filament_spools_barcode;
CREATE INDEX filament_spools_barcode ON filament_spools (barcode, created_at);

-- Removing a model sets `project_id` to NULL in the order lines that point at it: that looked through every order line.
CREATE INDEX order_lines_project_idx ON order_lines (project_id);

-- The pictures being made: the jobs of one batch in their order, and (for work that is left, only the rows that are left) the jobs that
-- have not finished, which every look at a model's pictures checks for ones that stopped moving.
CREATE INDEX ai_image_jobs_batch ON ai_image_jobs (batch_id, position);
CREATE INDEX ai_image_jobs_unfinished ON ai_image_jobs (updated_at) WHERE status IN ('queued', 'running');

-- The notifications held back by quiet hours: every worker asks for the ones that are due.
CREATE INDEX push_outbox_due ON push_outbox (deliver_after);
