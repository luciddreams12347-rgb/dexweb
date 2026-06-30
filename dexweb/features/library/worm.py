from .search import tokenize_topics


def _detect_grade(text, fallback):
    if fallback:
        return fallback
    lowered = text.lower()
    for grade in (9, 10, 11):
        if f"grade {grade}" in lowered or f"grade{grade}" in lowered:
            return grade
    return None


def _detect_subject(text, fallback):
    if fallback:
        return fallback
    lowered = text.lower()
    for subject in ("biology", "chemistry", "physics", "math", "history", "english"):
        if subject in lowered:
            return subject.title()
    return "General"


def run_worm_pipeline(dex_service, upload, extracted_text):
    ai_result = dex_service.process(
        prompt=(
            "Worm pipeline: clean content, deduplicate, detect grade/subject/topic, "
            "and suggest chapter/section placement."
        ),
        messages=[{"role": "user", "content": extracted_text[:2000]}],
        context={"feature": "library-worm", "upload_id": upload.id, "filename": upload.filename},
        user=upload.uploader,
    )
    normalized = " ".join(extracted_text.split())
    topics = tokenize_topics(normalized)[:8]
    subject = _detect_subject(normalized, upload.subject)
    grade = _detect_grade(normalized, upload.grade)
    chapter = upload.title.strip() if upload.title.strip() else (topics[0].title() if topics else "Overview")
    return {
        "extracted_text": normalized,
        "detected_subject": subject,
        "detected_grade": grade,
        "detected_topics": topics,
        "suggested_chapter": chapter,
        "suggested_section": "Core Concepts",
        "confidence": 0.72,
        "dex_result": ai_result.get("content", ""),
    }

