-- How long each part of a restore took, shown when it is done (where the time went). Added after 0022 had shipped, hence its own migration.
ALTER TABLE backup_jobs ADD COLUMN checking_seconds double precision;
ALTER TABLE backup_jobs ADD COLUMN replacing_seconds double precision;
