ALTER TABLE library_worm_jobs
  ADD COLUMN cancelled_at DATETIME NULL AFTER completed_at,
  ADD COLUMN cancelled_by VARCHAR(255) NULL AFTER cancelled_at;
