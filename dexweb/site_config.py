SITE_CONFIG = {
    "title": "DeX Web Tool",
    "brand": "DeX",
    "tagline": "Welcome to",
    "rooms": [
        {"key": "general", "label": "General", "grade": None},
        {"key": "grade9", "label": "Grade 9 Room", "grade": 9},
        {"key": "grade10", "label": "Grade 10 Room", "grade": 10},
        {"key": "grade11", "label": "Grade 11 Room", "grade": 11},
    ],
    "grade_tags": {
        9: {"label": "9", "color": "#2ecc71"},
        10: {"label": "10", "color": "#3498db"},
        11: {"label": "11", "color": "#9b59b6"},
    },
    "admin_tag": {"label": "ADMIN", "color": "#e74c3c"},
    "navigation": [
        {"endpoint": "main.cipher", "label": "Cypher Tool"},
        {"endpoint": "main.art", "label": "Art Tool"},
        {"endpoint": "main.chat_index", "label": "Chat Rooms"},
        {"endpoint": "main.admin_login", "label": "Admin", "variant": "danger"},
    ],
}
