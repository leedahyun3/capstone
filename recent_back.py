# recent_back.py
from __future__ import annotations

import os
import time
from typing import Dict, List
from flask import Flask, render_template, jsonify
from flask_cors import CORS

from recent import fetch_recent_results

app = Flask(__name__, template_folder="templates")
CORS(app)  # 배포 후 Netlify 도메인으로 제한해도 됨

TEAMS = ["한화", "LG", "롯데", "KIA", "SSG", "KT", "삼성", "NC", "두산", "키움"]

# 아주 짧은 TTL 캐시(부하/속도 개선; 완전 실시간이 아니어도 되면 권장)
_TTL = int(os.getenv("RECENT_TTL", "120"))  # 초
_cache: Dict[str, Dict[str, object]] = {}   # { team: {"ts": epoch, "data": List[str]} }

def _get_team_recent(team: str) -> List[str]:
    now = time.time()
    cached = _cache.get(team)
    if cached and now - cached["ts"] < _TTL:
        return cached["data"]  # 캐시 히트
    data = fetch_recent_results(team) or []
    # 길이 보정(5칸 유지)
    data = data[:5]
    if len(data) < 5:
        data += ["-"] * (5 - len(data))
    _cache[team] = {"ts": now, "data": data}
    return data


@app.route("/ping")
def ping():
    return "pong", 200


@app.route("/api/recent/<team>")
def api_recent(team: str):
    if team not in TEAMS:
        return jsonify({"error": "unknown team"}), 400
    return jsonify({"team": team, "results": _get_team_recent(team)})


@app.route("/")
def index():
    results = [{"team": t, "results": _get_team_recent(t)} for t in TEAMS]
    return render_template("recent.html", results=results)


def create_app():
    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
