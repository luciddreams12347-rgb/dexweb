CREATE TABLE IF NOT EXISTS library_grades (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  grade_level TINYINT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS library_subjects (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS library_uploads (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  uploader VARCHAR(80) NOT NULL,
  filename VARCHAR(255) NOT NULL,
  stored_path VARCHAR(500) NOT NULL,
  title VARCHAR(255) NULL,
  description TEXT NULL,
  grade_id INT NULL,
  subject_id INT NULL,
  status VARCHAR(40) NOT NULL DEFAULT 'pending',
  uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_library_uploads_uploader (uploader),
  INDEX idx_library_uploads_status (status),
  CONSTRAINT fk_library_uploads_grade FOREIGN KEY (grade_id) REFERENCES library_grades(id),
  CONSTRAINT fk_library_uploads_subject FOREIGN KEY (subject_id) REFERENCES library_subjects(id)
);

CREATE TABLE IF NOT EXISTS library_topics (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS library_review_queue (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  upload_id BIGINT UNSIGNED NOT NULL,
  extracted_text LONGTEXT NOT NULL,
  detected_subject_id INT NULL,
  detected_grade_id INT NULL,
  suggested_chapter VARCHAR(255) NOT NULL,
  suggested_section VARCHAR(255) NOT NULL,
  confidence DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
  status VARCHAR(40) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_library_review_upload FOREIGN KEY (upload_id) REFERENCES library_uploads(id),
  CONSTRAINT fk_library_review_subject FOREIGN KEY (detected_subject_id) REFERENCES library_subjects(id),
  CONSTRAINT fk_library_review_grade FOREIGN KEY (detected_grade_id) REFERENCES library_grades(id),
  INDEX idx_library_review_status (status)
);

CREATE TABLE IF NOT EXISTS library_review_topics (
  review_id BIGINT UNSIGNED NOT NULL,
  topic_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (review_id, topic_id),
  CONSTRAINT fk_library_review_topics_review FOREIGN KEY (review_id) REFERENCES library_review_queue(id),
  CONSTRAINT fk_library_review_topics_topic FOREIGN KEY (topic_id) REFERENCES library_topics(id)
);

CREATE TABLE IF NOT EXISTS library_books (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  grade_id INT NOT NULL,
  subject_id INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  is_published TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_library_books_grade_subject_title (grade_id, subject_id, title),
  CONSTRAINT fk_library_books_grade FOREIGN KEY (grade_id) REFERENCES library_grades(id),
  CONSTRAINT fk_library_books_subject FOREIGN KEY (subject_id) REFERENCES library_subjects(id)
);

CREATE TABLE IF NOT EXISTS library_chapters (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  book_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(255) NOT NULL,
  sequence_num INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_library_chapters_book FOREIGN KEY (book_id) REFERENCES library_books(id),
  INDEX idx_library_chapters_book_seq (book_id, sequence_num)
);

CREATE TABLE IF NOT EXISTS library_sections (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  chapter_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(255) NOT NULL,
  content LONGTEXT NOT NULL,
  sequence_num INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_library_sections_chapter FOREIGN KEY (chapter_id) REFERENCES library_chapters(id),
  INDEX idx_library_sections_chapter_seq (chapter_id, sequence_num)
);

CREATE TABLE IF NOT EXISTS library_section_topics (
  section_id BIGINT UNSIGNED NOT NULL,
  topic_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (section_id, topic_id),
  CONSTRAINT fk_library_section_topics_section FOREIGN KEY (section_id) REFERENCES library_sections(id),
  CONSTRAINT fk_library_section_topics_topic FOREIGN KEY (topic_id) REFERENCES library_topics(id)
);

CREATE TABLE IF NOT EXISTS library_versions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  chapter_id BIGINT UNSIGNED NOT NULL,
  version_number INT NOT NULL,
  changed_by VARCHAR(80) NOT NULL,
  snapshot_json LONGTEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_library_versions_chapter_version (chapter_id, version_number),
  CONSTRAINT fk_library_versions_chapter FOREIGN KEY (chapter_id) REFERENCES library_chapters(id)
);

CREATE TABLE IF NOT EXISTS library_sources (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  section_id BIGINT UNSIGNED NOT NULL,
  upload_id BIGINT UNSIGNED NOT NULL,
  source_location VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_library_sources_section FOREIGN KEY (section_id) REFERENCES library_sections(id),
  CONSTRAINT fk_library_sources_upload FOREIGN KEY (upload_id) REFERENCES library_uploads(id),
  INDEX idx_library_sources_section (section_id)
);

CREATE TABLE IF NOT EXISTS library_suggestions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  suggestion_type VARCHAR(80) NOT NULL,
  payload_json LONGTEXT NOT NULL,
  status VARCHAR(40) NOT NULL DEFAULT 'open',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_by VARCHAR(80) NULL,
  reviewed_at DATETIME NULL,
  INDEX idx_library_suggestions_status (status)
);

