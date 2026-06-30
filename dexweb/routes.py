from flask import Blueprint, current_app


main = Blueprint("main", __name__)


@main.app_context_processor
def inject_site():
    return {"site": current_app.config["SITE"]}


def register_routes():
    from .features.admin import routes as admin_routes  # noqa: F401
    from .features.auth import routes as auth_routes  # noqa: F401
    from .features.chat import routes as chat_routes  # noqa: F401
    from .features.core import routes as core_routes  # noqa: F401
    from .features.dex import routes as dex_routes  # noqa: F401
    from .features.library import routes as library_routes  # noqa: F401
    from .features.tools import routes as tools_routes  # noqa: F401
