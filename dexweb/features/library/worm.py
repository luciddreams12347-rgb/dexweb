import concurrent.futures
import json
import re

from flask import current_app

from dexweb.features.dex.ollama_client import OllamaCancelledError

from .search import tokenize_topics


WORM_METADATA_PROMPT = (
    "Analyze educational source material for library metadata only. "
    "Do NOT rewrite, paraphrase, summarize, improve, or correct the source content. "
    "Return ONLY valid JSON with keys: subject, topic, grade, suggested_sections, confidence. "
    "Optional keys: difficulty, duplicate_hint."
)


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


def _parse_ai_metadata(content):
    if not content:
        return {}
    text = content.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_grade(value, fallback):
    if value in (None, ""):
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_confidence(value, fallback=0.72):
    if value in (None, ""):
        return fallback
    try:
        score = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, score))


def _cancelled(cancel_check):
    return bool(cancel_check and cancel_check())


def run_worm_pipeline_timed(dex_service, upload, extracted_text, timeout, cancel_check=None):
    from flask import current_app

    if _cancelled(cancel_check):
        raise OllamaCancelledError("Worm job cancelled before AI processing.")

    app = current_app._get_current_object()

    def run_in_context():
        with app.app_context():
            if _cancelled(cancel_check):
                raise OllamaCancelledError("Worm job cancelled before AI processing.")
            return run_worm_pipeline(dex_service, upload, extracted_text, cancel_check=cancel_check)

    if timeout is None:
        return run_in_context()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_in_context)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(f"Worm AI processing exceeded {timeout}s timeout") from exc


def run_worm_pipeline(dex_service, upload, extracted_text, cancel_check=None):
    if _cancelled(cancel_check):
        raise OllamaCancelledError("Worm job cancelled before AI processing.")

    original_text = extracted_text
    ai_result = dex_service.process(
        prompt=WORM_METADATA_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract metadata from this source material. "
                    "Do not rewrite or modify the educational content.\n\n"
                    f"{original_text[:4000]}"
                ),
            }
        ],
        context={"feature": "library-worm", "upload_id": upload.id, "filename": upload.filename, "task": "metadata-only"},
        user=upload.uploader,
        cancel_check=cancel_check,
    )
    if _cancelled(cancel_check):
        raise OllamaCancelledError("Worm job cancelled after AI processing.")

    if not ai_result.get("ok"):
        raise RuntimeError(ai_result.get("error") or "Worm AI processing failed.")

    parsed = _parse_ai_metadata(ai_result.get("content", ""))
    topics = tokenize_topics(original_text)[:8]
    subject = (parsed.get("subject") or _detect_subject(original_text, upload.subject) or "General").strip() or "General"
    grade = _coerce_grade(parsed.get("grade"), _detect_grade(original_text, upload.grade))
    topic = (parsed.get("topic") or (topics[0] if topics else "")).strip()
    suggested_sections = parsed.get("suggested_sections") or []
    if not isinstance(suggested_sections, list):
        suggested_sections = []
    suggested_sections = [str(item).strip() for item in suggested_sections if str(item).strip()]
    chapter = upload.title.strip() if upload.title.strip() else (topic.title() if topic else (topics[0].title() if topics else "Overview"))
    suggested_section = suggested_sections[0] if suggested_sections else "Core Concepts"
    confidence = _coerce_confidence(parsed.get("confidence"))
    ai_suggestions = {
        "subject": subject,
        "topic": topic,
        "grade": grade,
        "suggested_sections": suggested_sections,
        "suggested_chapter": chapter,
        "suggested_section": suggested_section,
        "confidence": confidence,
        "difficulty": parsed.get("difficulty"),
        "duplicate_hint": parsed.get("duplicate_hint"),
    }
    return {
        "extracted_text": original_text,
        "detected_subject": subject,
        "detected_grade": grade,
        "detected_topics": topics,
        "suggested_chapter": chapter,
        "suggested_section": suggested_section,
        "confidence": confidence,
        "ai_suggestions": ai_suggestions,
    }
