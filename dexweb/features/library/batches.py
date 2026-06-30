from werkzeug.datastructures import FileStorage


def split_upload_path(filename):
    normalized = (filename or "").replace("\\", "/").strip()
    if "/" in normalized:
        folder_path, basename = normalized.rsplit("/", 1)
        return folder_path.strip(), basename.strip()
    return "", normalized.strip()


def collect_upload_files(request):
    files = []
    seen = set()
    single = request.files.get("file")
    if single and single.filename:
        seen.add(single.filename)
        files.append(single)
    for field_name in ("files", "folder_files"):
        for item in request.files.getlist(field_name):
            if item and item.filename and item.filename not in seen:
                seen.add(item.filename)
                files.append(item)
    return files


def detect_source_type(files):
    if not files:
        return "single"
    if any("/" in (item.filename or "") or "\\" in (item.filename or "") for item in files):
        return "folder"
    if len(files) > 1:
        return "multi"
    return "single"


def batch_title_from_files(files, form_title=""):
    title = (form_title or "").strip()
    if title:
        return title
    for item in files:
        folder_path, _ = split_upload_path(item.filename or "")
        if folder_path:
            return folder_path.split("/")[0]
    if len(files) == 1:
        _, basename = split_upload_path(files[0].filename or "")
        return basename.rsplit(".", 1)[0] if basename else "Upload batch"
    return "Upload batch"


def folder_path_for_file(file_storage: FileStorage):
    folder_path, _ = split_upload_path(file_storage.filename or "")
    return folder_path
