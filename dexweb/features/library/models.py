from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)


@dataclass
class UploadRecord:
    id: int
    uploader: str
    filename: str
    stored_path: str
    grade: int | None
    subject: str
    title: str
    description: str
    uploaded_at: datetime = field(default_factory=utcnow)
    status: str = "pending"


@dataclass
class ReviewItem:
    id: int
    upload_id: int
    extracted_text: str
    detected_subject: str
    detected_grade: int | None
    detected_topics: list[str]
    suggested_chapter: str
    suggested_section: str
    confidence: float
    source_file: str
    status: str = "pending"
    created_at: datetime = field(default_factory=utcnow)

