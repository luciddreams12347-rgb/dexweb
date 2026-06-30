import re


def tokenize_topics(text):
    words = [item.lower() for item in re.findall(r"[a-zA-Z]{4,}", text)]
    seen = set()
    out = []
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def section_matches(section, grade=None, subject=None, topic=None, keyword=None):
    if grade is not None and section.get("grade") != grade:
        return False
    if subject and section.get("subject", "").lower() != subject.lower():
        return False
    haystack = " ".join(
        [
            section.get("chapter_title", ""),
            section.get("title", ""),
            section.get("content", ""),
            " ".join(section.get("topics", [])),
        ]
    ).lower()
    if topic and topic.lower() not in haystack:
        return False
    if keyword and keyword.lower() not in haystack:
        return False
    return True

