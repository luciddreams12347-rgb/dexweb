from flask import Flask

from .config import DexwebConfig
from .routes import main, register_routes


def create_app(test_config=None):
    instance_path = test_config.get("INSTANCE_PATH") if test_config and test_config.get("INSTANCE_PATH") else None
    app = Flask(__name__, template_folder="templates", static_folder="static", instance_path=instance_path)
    app.config.from_object(DexwebConfig)
    if test_config:
        app.config.update(test_config)
    app.config["SITE"] = app.config["SITE_CONFIG"]
    register_routes()
    app.register_blueprint(main)
    return app
