# team_ranking_back_alt.py
import os
import json
import threading
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, send_file, jsonify, abort, Response
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from jinja2 import TemplateNotFound

from team_ranking_alt import fetch_team_rankings
from hour_back_alt import hour_bp  # ⬅️ 평균 경기시간 블루프린트

app = Flask(__name__, template_folder="templates")
app.register_blueprint(hour_bp)  # /hour 활성화

# ---- 설정 ----
CACHE_INTERVAL_MIN = int(os.getenv("CACHE_INTERVAL_MIN", "5"))
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN", "")
CACHE_FILE = os.getenv("CACHE_FILE", os.path.join(os.getcwd(), "cache.json"))

# ---- 메모리 캐시 ----
_cache_lock = threading.Lock()
_cache_data = {"rankings": [], "updated_at": None}

# ============== 유틸 ==============
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
        print(f"[CACHE] loaded ({CACHE_FILE}), updated_at={updated_at}")
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
        print(f"[CACHE] saved ({CACHE_FILE})")
    except Exception as e:
        print(f"[CACHE] save error: {e}")

# ============== 캐시 갱신 ==============
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
    try:
        return render_template("combined.html")  # 아래 템플릿 추가
    except TemplateNotFound:
        # 템플릿 누락 시에도 빈 화면 대신 안내
        return (
            '<h3>대시보드 준비됨</h3>'
            '<p><a href="/team-ranking">팀 순위</a> · <a href="/hour">평균 경기시간</a></p>',
            200,
        )

# ============== 팀 순위 뷰 ==============
@app.route("/team-ranking")
def show_ranking():
    # 1) 메모리에서 읽기
    with _cache_lock:
        rankings = list(_cache_data["rankings"])
        updated_at = _cache_data["updated_at"]

    # 2) 비어 있으면 디스크 → 즉시 갱신까지 시도
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

    # 3) 템플릿 렌더 (없으면 폴백)
    try:
        return render_template("team_ranking_alt.html", rankings=rankings, updated_at=updated_at)
    except TemplateNotFound:
        # 템플릿이 누락돼도 기본 표로 표시
        head = "<h3 style='margin:8px 0 12px'>팀 순위 (템플릿 없음: 기본 표)</h3>"
        if not rankings:
            return head + "<div>데이터가 아직 없습니다. 잠시 후 새로고침 해주세요.</div>"
        # 컬럼 자동 생성
        cols = list(rankings[0].keys())
        thead = "<thead><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr></thead>"
        rows = []
        for r in rankings:
            rows.append("<tr>" + "".join(f"<td>{r.get(c, '')}</td>" for c in cols) + "</tr>")
        table = f"<table border='1' cellpadding='6' cellspacing='0'>{thead}<tbody>{''.join(rows)}</tbody></table>"
        return head + table

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
        return jsonify({"updated_at": None, "rankings": []})

@app.route("/refresh", methods=["POST", "GET"])
def manual_refresh():
    if REFRESH_TOKEN:
        token = request.args.get("token") or request.headers.get("X-Refresh-Token", "")
        if token != REFRESH_TOKEN:
            return abort(401)
    refresh_cache()
    with _cache_lock:
        payload = {"ok": True, "updated_at": _dt_to_iso(_cache_data["updated_at"])}
    return jsonify(payload)

@app.route("/proxy-logo")
def proxy_logo():
    url = request.args.get("url")
    if not url:
        return "Missing URL", 400
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

# 로컬 실행용
if __name__ == "__main__":
    load_cache_from_disk()
    if not _cache_data["rankings"]:
        refresh_cache()
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
