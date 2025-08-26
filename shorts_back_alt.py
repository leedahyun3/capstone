# shorts_back_alt.py
from __future__ import annotations

import os
from flask import Flask, Blueprint, render_template
from shorts_alt import fetch_kbo_shorts_alt

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
shorts_bp = Blueprint("shorts_alt", __name__, template_folder=TEMPLATE_DIR)

@shorts_bp.route("/shorts/ping")
def ping():
    return "pong", 200

@shorts_bp.route("/shorts")
def show_shorts():
    shorts = fetch_kbo_shorts_alt()
    return render_template("shorts_alt.html", shorts=shorts)

def create_app():
    app = Flask(__name__)
    app.register_blueprint(shorts_bp)
    return app

if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5004, debug=True)
