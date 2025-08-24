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

app = Flask(__name__, template_folder="templates")

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
    """서버 부팅/콜드스타트 시, 디스크의 JSON 캐시를 메모리로 로드."""
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
    """메모리 캐시를 JSON으로 디스크에 원자적으로 저장."""
    try:
        tmp_path = CACHE_FILE + ".tmp"
        with _cache_lock:
            payload = {
                "updated_at": _dt_to_iso(_cache_data["updated_at"]),
                "rankings": _cache_data["rankings"],
            }
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CACHE_FILE)  # 원자적 교체
        # 권한(선택): 읽기 전용으로 완화
        try:
            os.chmod(CACHE_FILE, 0o644)
        except Exception:
            pass
        print(f"[CACHE] saved to disk ({CACHE_FILE})")
    except Exception as e:
        print(f"[CACHE] save error: {e}")


# ============== 캐시 갱신 로직 ==============

def refresh_cache():
    """크롤링 → 메모리 캐시 갱신 → 디스크 저장."""
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


# ============== 라우팅 ==============

@app.route("/team-ranking")
def show_ranking():
    with _cache_lock:
        rankings = list(_cache_data["rankings"])
        updated_at = _cache_data["updated_at"]
    if not rankings:
        # 콜드스타트: 먼저 디스크에서 로드 시도
        load_cache_from_disk()
        with _cache_lock:
            rankings = list(_cache_data["rankings"])
            updated_at = _cache_data["updated_at"]
        # 그래도 없으면 즉시 1회 크롤
        if not rankings:
            refresh_cache()
            with _cache_lock:
                rankings = list(_cache_data["rankings"])
                updated_at = _cache_data["updated_at"]
    return render_template("team_ranking_alt.html", rankings=rankings, updated_at=updated_at)

@app.route("/team-ranking.json")
def show_ranking_json():
    """메모리 캐시를 JSON으로 반환(실시간 상태)."""
    with _cache_lock:
        payload = {
            "updated_at": _dt_to_iso(_cache_data["updated_at"]),
            "rankings": _cache_data["rankings"],
        }
    return jsonify(payload)

@app.route("/cache.json")
def download_cache_json():
    """
    디스크에 저장된 JSON 파일을 그대로 반환(사람이 보기 좋은 pretty JSON).
    파일이 없으면 빈 구조 반환.
    """
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
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
            )
        }
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            return f"Image fetch failed with status {response.status_code}", 502
        return send_file(BytesIO(response.content), mimetype="image/png")
    except Exception as e:
        return f"Error fetching image: {str(e)}", 500


# ============== 부팅 시 동작 ==============

if __name__ == "__main__":
    # 1) 디스크 캐시 선로드(있다면)
    load_cache_from_disk()
    # 2) 첫 갱신 시도(없을 때 대비)
    if not _cache_data["rankings"]:
        refresh_cache()
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
