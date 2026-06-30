import hashlib
import mimetypes
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "png", "jpg", "jpeg", "webp", "gif"}
ALLOWED_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    ".txt": {"text/plain"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".gif": {"image/gif"},
}


def allowed_upload(filename):
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def uploads_root():
    configured = current_app.config.get("LIBRARY_UPLOADS_DIR", "").strip()
    if configured:
        root = Path(configured)
    else:
        root = Path(current_app.instance_path) / "library_uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _max_upload_bytes():
    return int(current_app.config.get("LIBRARY_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))


def split_upload_path(filename):
    normalized = (filename or "").replace("\\", "/").strip()
    if "/" in normalized:
        folder_path, basename = normalized.rsplit("/", 1)
        return folder_path.strip(), basename.strip()
    return "", normalized.strip()


def validate_upload(file_storage: FileStorage):
    original_filename = file_storage.filename or ""
    if not original_filename:
        raise ValueError("Select a file to upload.")
    folder_path, basename = split_upload_path(original_filename)
    if not basename:
        raise ValueError("Invalid filename.")
    if not allowed_upload(basename):
        raise ValueError("Unsupported file type.")
    safe_name = secure_filename(basename)
    if not safe_name:
        raise ValueError("Invalid filename.")
    suffix = Path(safe_name).suffix.lower()
    detected_mime = (file_storage.mimetype or "").lower()
    allowed = ALLOWED_MIME_TYPES.get(suffix, set())
    guessed_mime, _ = mimetypes.guess_type(safe_name)
    if detected_mime and detected_mime not in allowed and detected_mime != "application/octet-stream":
        raise ValueError("Uploaded file type does not match its extension.")

    stream = file_storage.stream
    stream.seek(0)
    content = stream.read()
    stream.seek(0)
    size = len(content)
    if size <= 0:
        raise ValueError("Uploaded file is empty.")
    if size > _max_upload_bytes():
        raise ValueError("Uploaded file is too large.")
    digest = hashlib.sha256(content).hexdigest()
    return {
        "original_filename": basename,
        "original_path": original_filename,
        "folder_path": folder_path,
        "safe_filename": safe_name,
        "mime_type": detected_mime or guessed_mime or "application/octet-stream",
        "file_size": size,
        "sha256": digest,
        "suffix": suffix,
    }


def save_upload(file_storage: FileStorage):
    metadata = validate_upload(file_storage)
    unique_name = f"{uuid.uuid4().hex}{metadata['suffix']}"
    target = uploads_root() / unique_name
    file_storage.save(target)
    metadata["stored_filename"] = unique_name
    metadata["stored_path"] = str(target)
    return metadata


def load_upload_text(path):
    source = Path(path)
    if not source.exists():
        raise OSError("Uploaded file is missing.")
    suffix = source.suffix.lower()
    if suffix == ".txt":
        return source.read_text(encoding="utf-8", errors="replace")
    # V1 production fallback for binary formats pending richer OCR/document parsing.
    return f"Uploaded source file: {source.name}"

