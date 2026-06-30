CREATE TABLE IF NOT EXISTS library_worm_jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  upload_id BIGINT UNSIGNED NOT NULL,
  status VARCHAR(40) NOT NULL DEFAULT 'pending',
  started_at DATETIME NULL,
  completed_at DATETIME NULL,
  error_message TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_library_worm_jobs_upload FOREIGN KEY (upload_id) REFERENCES library_uploads(id),
  INDEX idx_library_worm_jobs_status (status),
  INDEX idx_library_worm_jobs_upload (upload_id)
);
