# team_ranking_back_alt.py
import os
import json
import threading
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, send_file, jsonify, abort, Response
from apscheduler.schedulers.background import BackgroundScheduler
import requests

from team_ranking_alt import fetch_team_rankings

# ✅ 평균 경기시간 블루프린트 임포트
from hour_back_alt import hour_bp

app = Flask(__name__, template_folder="templates")

# ✅ 블루프린트 등록 (/hour 경로 활성화)
app.register_blueprint(hour_bp)

# ---- 설정 ----
CACHE_INTERVAL_MIN = int(os.getenv("CACHE_INTERVAL_MIN", "5"))          # 주기(분)
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN", "")                          # /refresh 보호용
CACHE_FILE = os.getenv("CACHE_FILE", os.path.join(os.getcwd(), "cache.json"))

# ---- 메모리 캐시 ----
_cache_lock = threading.Lock()
_cache_data = {"rankings": [], "updated_at": None}  # updated_at: datetime | None

# ============== 디스크 캐시 유틸 ==============
def _dt_to_iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else None

def _iso_to_dt(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except Exception:
        return None

def load_cache_from_disk():
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        rankings = obj.get("rankings", [])
        updated_at = _iso_to_dt(obj.get("updated_at"))
        with _cache_lock:
            _cache_data["rankings"] = rankings
            _cache_data["updated_at"] = updated_at
        print(f"[CACHE] loaded from disk ({CACHE_FILE}), updated_at={updated_at}")
    except Exception as e:
        print(f"[CACHE] load error: {e}")

def save_cache_to_disk():
    try:
        tmp_path = CACHE_FILE + ".tmp"
        with _cache_lock:
            payload = {
                "updated_at": _dt_to_iso(_cache_data["updated_at"]),
                "rankings": _cache_data["rankings"],
            }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CACHE_FILE)
        try:
            os.chmod(CACHE_FILE, 0o644)
        except Exception:
            pass
        print(f"[CACHE] saved to disk ({CACHE_FILE})")
    except Exception as e:
        print(f"[CACHE] save error: {e}")

# ============== 캐시 갱신 로직 ==============
def refresh_cache():
    global _cache_data
    try:
        data = fetch_team_rankings()
        if data:
            with _cache_lock:
                _cache_data["rankings"] = data
                _cache_data["updated_at"] = datetime.now()
            print(f"[CACHE] refreshed at {_cache_data['updated_at']}")
            save_cache_to_disk()
        else:
            print("[CACHE] fetch returned empty; keep old cache.")
    except Exception as e:
        print(f"[CACHE] refresh error: {e}")

# ============== 스케줄러 ==============
scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(refresh_cache, "interval", minutes=CACHE_INTERVAL_MIN, next_run_time=datetime.now())
scheduler.start()

# ============== 루트: 통합 페이지 ==============
@app.route("/", methods=["GET"])
def dashboard():
    return render_template("combined.html")  # templates/combined.html

# ============== 라우팅(팀 순위 단독 페이지) ==============
@app.route("/team-ranking")
def show_ranking():
    with _cache_lock:
        rankings = list(_cache_data["rankings"])
        updated_at = _cache_data["updated_at"]
    if not rankings:
        load_cache_from_disk()
        with _cache_lock:
            rankings = list(_cache_data["rankings"])
            updated_at = _cache_data["updated_at"]
        if not rankings:
            refresh_cache()
            with _cache_lock:
                rankings = list(_cache_data["rankings"])
                updated_at = _cache_data["updated_at"]
    return render_template("team_ranking_alt.html", rankings=rankings, updated_at=updated_at)

@app.route("/team-ranking.json")
def show_ranking_json():
    with _cache_lock:
        payload = {
            "updated_at": _dt_to_iso(_cache_data["updated_at"]),
            "rankings": _cache_data["rankings"],
        }
    return jsonify(payload)

@app.route("/cache.json")
def download_cache_json():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            raw = f.read()
        return Response(raw, mimetype="application/json; charset=utf-8")
    else:
        empty = {"updated_at": None, "rankings": []}
        return jsonify(empty)

@app.route("/refresh", methods=["POST", "GET"])
def manual_refresh():
    if REFRESH_TOKEN:
        token = request.args.get("token") or request.headers.get("X-Refresh-Token", "")
        if token != REFRESH_TOKEN:
            return abort(401)
    refresh_cache()
    with _cache_lock:
        payload = {
            "ok": True,
            "updated_at": _dt_to_iso(_cache_data["updated_at"])
        }
    return jsonify(payload)

@app.route("/proxy-logo")
def proxy_logo():
    url = request.args.get("url")
    if not url:
        return "Missing URL", 400
    try:
        headers = {
            "Referer": "https://sports.naver.com",
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
                "AppleWebKit(605.1.15) (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
            )
        }
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            return f"Image fetch failed with status {response.status_code}", 502
        return send_file(BytesIO(response.content), mimetype="image/png")
    except Exception as e:
        return f"Error fetching image: {str(e)}", 500

# ============== 부팅 시 동작 (로컬 실행용) ==============
if __name__ == "__main__":
    load_cache_from_disk()
    if not _cache_data["rankings"]:
        refresh_cache()
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
