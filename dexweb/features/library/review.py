def normalize_admin_action(action):
    allowed = {
        "approve",
        "reject",
        "reprocess",
        "publish",
        "unpublish",
        "rename_chapter",
        "change_subject",
        "change_grade",
        "merge",
        "split",
        "move",
        "edit",
        "restore",
    }
    return action if action in allowed else ""

