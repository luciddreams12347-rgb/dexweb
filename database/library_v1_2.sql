CREATE TABLE IF NOT EXISTS library_upload_batches (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  uploader VARCHAR(80) NOT NULL,
  title VARCHAR(255) NOT NULL,
  source_type VARCHAR(40) NOT NULL DEFAULT 'multi',
  status VARCHAR(40) NOT NULL DEFAULT 'processing',
  total_files INT UNSIGNED NOT NULL DEFAULT 0,
  processed_files INT UNSIGNED NOT NULL DEFAULT 0,
  failed_files INT UNSIGNED NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_library_batches_uploader (uploader),
  INDEX idx_library_batches_status (status)
);

ALTER TABLE library_uploads
  ADD COLUMN batch_id BIGINT UNSIGNED NULL AFTER id,
  ADD COLUMN folder_path VARCHAR(500) NULL AFTER stored_path;

ALTER TABLE library_uploads
  ADD CONSTRAINT fk_library_uploads_batch FOREIGN KEY (batch_id) REFERENCES library_upload_batches(id);
