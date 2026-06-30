from flask import redirect, render_template, session, url_for

from ...routes import main
from ..auth.session import login_required


@main.route("/")
def index():
    return render_template("index.html")


@main.route("/home")
def home():
    if not login_required():
        return redirect(url_for("main.login"))
    return render_template("home.html", user=session["user"])
