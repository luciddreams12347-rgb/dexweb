import os

from dexweb import create_app


app = create_app()


if __name__ == "__main__":
    debug = os.environ.get("DEX_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug)
