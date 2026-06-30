from flask import render_template, redirect, request, session, url_for

from ...database import is_banned, log_action
from ...routes import main
from ..auth.session import login_required
from .cipher_service import decode, encode

try:
    import pyfiglet
except ImportError:  # pragma: no cover
    pyfiglet = None


@main.route("/cipher", methods=["GET", "POST"])
def cipher():
    if not login_required():
        return redirect(url_for("main.login"))
    if is_banned(session["user"], "cipher"):
        return render_template("message.html", message="You are banned from Cipher Tool."), 403
    text = result = ""
    if request.method == "POST":
        text = request.form.get("text", "")
        if request.form.get("action") == "encode":
            result = encode(text)
        elif request.form.get("action") == "decode":
            result = decode(text)
        log_action(session["user"], "Used Cipher Tool")
    return render_template("cipher.html", text=text, result=result)


@main.route("/art", methods=["GET", "POST"])
def art():
    if not login_required():
        return redirect(url_for("main.login"))
    if is_banned(session["user"], "art"):
        return render_template("message.html", message="You are banned from Art Tool."), 403
    text = result = ""
    if request.method == "POST":
        text = request.form.get("text", "")
        if text:
            result = pyfiglet.figlet_format(text) if pyfiglet else "(figlet not available)"
            log_action(session["user"], "Used Art Tool")
    return render_template("art.html", text=text, result=result)
