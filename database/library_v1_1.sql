ALTER TABLE library_uploads
  ADD COLUMN original_filename VARCHAR(255) NULL AFTER filename,
  ADD COLUMN mime_type VARCHAR(120) NULL AFTER stored_path,
  ADD COLUMN file_size BIGINT UNSIGNED NOT NULL DEFAULT 0 AFTER mime_type,
  ADD COLUMN sha256 CHAR(64) NULL AFTER file_size;

ALTER TABLE library_uploads
  ADD UNIQUE KEY uq_library_uploads_uploader_sha256 (uploader, sha256);

ALTER TABLE library_sources
  ADD INDEX idx_library_sources_upload (upload_id);

ALTER TABLE library_versions
  ADD INDEX idx_library_versions_created_at (created_at);
