import os
import json
import threading
from datetime import datetime, timedelta
from io import BytesIO

from flask import Flask, render_template, request, send_file, jsonify, abort, Response
import requests
from jinja2 import TemplateNotFound

from team_ranking_alt import fetch_team_rankings
from hour_back_alt import hour_bp  # ⬅️ /hour 블루프린트

app = Flask(__name__, template_folder="templates")
app.register_blueprint(hour_bp)

# ---- 설정 ----
CACHE_FILE = os.getenv("CACHE_FILE", os.path.join(os.getcwd(), "cache.json"))
CACHE_TTL_MIN = int(os.getenv("CACHE_TTL_MIN", "10"))  # TTL 방식으로만 갱신
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN", "")

# ---- 메모리 캐시 ----
_cache_lock = threading.Lock()
_cache_data = {"rankings": [], "updated_at": None}  # updated_at: datetime | None

# ============== 유틸 ==============
def _dt_to_iso(dt): return dt.isoformat() if isinstance(dt, datetime) else None
def _iso_to_dt(s):
    try: return datetime.fromisoformat(s) if s else None
    except Exception: return None

def load_cache_from_disk():
    if not os.path.exists(CACHE_FILE): return
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f: obj = json.load(f)
        with _cache_lock:
            _cache_data["rankings"] = obj.get("rankings", [])
            _cache_data["updated_at"] = _iso_to_dt(obj.get("updated_at"))
        print(f"[CACHE] loaded ({CACHE_FILE}), updated_at={_cache_data['updated_at']}")
    except Exception as e:
        print(f"[CACHE] load error: {e}")

def save_cache_to_disk():
    try:
        tmp = CACHE_FILE + ".tmp"
        with _cache_lock:
            payload = {"updated_at": _dt_to_iso(_cache_data["updated_at"]),
                       "rankings": _cache_data["rankings"]}
        with open(tmp, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
        try: os.chmod(CACHE_FILE, 0o644)
        except Exception: pass
        print(f"[CACHE] saved ({CACHE_FILE})")
    except Exception as e:
        print(f"[CACHE] save error: {e}")

def refresh_cache():
    try:
        data = fetch_team_rankings()
        if data:
            with _cache_lock:
                _cache_data["rankings"] = data
                _cache_data["updated_at"] = datetime.now()
            save_cache_to_disk()
            print(f"[CACHE] refreshed at {_cache_data['updated_at']}")
        else:
            print("[CACHE] fetch returned empty; keep old cache")
    except Exception as e:
        print(f"[CACHE] refresh error: {e}")

def cache_stale():
    with _cache_lock:
        ts = _cache_data["updated_at"]
    if ts is None: return True
    return datetime.now() - ts > timedelta(minutes=CACHE_TTL_MIN)

# ============== 헬스 & 루트 ==============
@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/", methods=["GET"])
def dashboard():
    try:
        return render_template("combined.html")
    except TemplateNotFound:
        return ('<h3>대시보드</h3>'
                '<p><a href="/team-ranking">팀 순위</a> · <a href="/hour">평균 경기시간</a></p>', 200)

# ============== 팀 순위 ==============
@app.route("/team-ranking")
def show_ranking():
    if cache_stale():
        refresh_cache()

    with _cache_lock:
        rankings = list(_cache_data["rankings"]); updated_at = _cache_data["updated_at"]

    try:
        return render_template("team_ranking_alt.html", rankings=rankings, updated_at=updated_at)
    except TemplateNotFound:
        if not rankings:
            return "<div>팀 순위 데이터가 아직 없습니다. 잠시 후 새로고침 해주세요.</div>", 200
        cols = list(rankings[0].keys())
        thead = "<thead><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead>"
        rows = ["<tr>" + "".join(f"<td>{r.get(c, '')}</td>" for c in cols) + "</tr>" for r in rankings]
        return "<h3>팀 순위</h3>" + f"<table border='1' cellpadding='6' cellspacing='0'>{thead}<tbody>{''.join(rows)}</tbody></table>"

@app.route("/team-ranking.json")
def show_ranking_json():
    with _cache_lock:
        return jsonify({"updated_at": _dt_to_iso(_cache_data["updated_at"]),
                        "rankings": _cache_data["rankings"]})

@app.route("/cache.json")
def download_cache_json():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f: raw = f.read()
        return Response(raw, mimetype="application/json; charset=utf-8")
    else:
        return jsonify({"updated_at": None, "rankings": []})

@app.route("/refresh", methods=["POST", "GET"])
def manual_refresh():
    if REFRESH_TOKEN:
        token = request.args.get("token") or request.headers.get("X-Refresh-Token", "")
        if token != REFRESH_TOKEN: return abort(401)
    refresh_cache()
    with _cache_lock:
        return jsonify({"ok": True, "updated_at": _dt_to_iso(_cache_data["updated_at"])})

@app.route("/proxy-logo")
def proxy_logo():
    url = request.args.get("url")
    if not url: return "Missing URL", 400
    try:
        headers = {
            "Referer": "https://sports.naver.com",
            "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1")
        }
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            return f"Image fetch failed with status {response.status_code}", 502
        return send_file(BytesIO(response.content), mimetype="image/png")
    except Exception as e:
        return f"Error fetching image: {str(e)}", 500

# ============== 부팅 시 ==============
load_cache_from_disk()
if not _cache_data["rankings"]:
    refresh_cache()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

