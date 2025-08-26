# hour_back_alt.py
from __future__ import annotations

import os, re, platform, time, json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Set

import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, Blueprint, request, render_template
from jinja2 import TemplateNotFound
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ---------- 환경/상수 ----------
TOP30   = float(os.getenv("TOP30_MINUTES", "168"))
AVG_REF = float(os.getenv("AVG_REF_MINUTES", "182.7"))
BOTTOM70= float(os.getenv("BOTTOM70_MINUTES", "194"))
MAX_LOOKBACK_DAYS = int(os.getenv("MAX_LOOKBACK_DAYS", "90"))

# JSON 캐시 경로(로컬 개발/DB 미사용 시에만 사용)
RUNTIME_CACHE_FILE  = os.getenv("RUNTIME_CACHE_FILE", "runtime_cache.json")
SCHEDULE_CACHE_FILE = os.getenv("SCHEDULE_CACHE_FILE", "schedule_index.json")

# hour_alt.html / hour.html 등 템플릿 이름 선택 가능
HOUR_TEMPLATE = os.getenv("HOUR_TEMPLATE", "hour_alt.html")

# ---------- JSON 캐시 유틸 ----------
def _load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def _save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def get_runtime_cache():
    return _load_json(RUNTIME_CACHE_FILE, {})

def set_runtime_cache(key, runtime_min):
    cache = get_runtime_cache()
    cache[key] = {"runtime_min": runtime_min}
    _save_json(RUNTIME_CACHE_FILE, cache)

def get_schedule_cache():
    return _load_json(SCHEDULE_CACHE_FILE, {})

def set_schedule_cache_for_date(date_str, games_minimal_list):
    cache = get_schedule_cache()
    cache[date_str] = games_minimal_list
    _save_json(SCHEDULE_CACHE_FILE, cache)

def make_runtime_key(game_id, game_date):
    return f"{game_id}_{game_date}"

# ---------- PostgreSQL 백엔드 (DATABASE_URL 있으면 사용) ----------
DB_URL = os.getenv("DATABASE_URL")
if DB_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def _pg_conn():
        return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

    def get_runtime_cache_entry(key: str):
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT runtime_min FROM runtime_cache WHERE key=%s", (key,))
            row = cur.fetchone()
            return {"runtime_min": row["runtime_min"]} if row else None

    def set_runtime_cache_entry(key: str, runtime_min: int):
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO runtime_cache(key, runtime_min) VALUES (%s,%s)
                ON CONFLICT (key) DO UPDATE SET runtime_min = EXCLUDED.runtime_min, updated_at = now()
            """, (key, runtime_min))
            conn.commit()

    def get_schedule_cache_for_date_pg(date_str: str):
        ds = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str)==8 and date_str.isdigit() else date_str
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT payload FROM schedule_cache WHERE date_str=%s::date", (ds,))
            row = cur.fetchone()
            return row["payload"] if row else None

    def set_schedule_cache_for_date_pg(date_str: str, payload: list):
        ds = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str)==8 and date_str.isdigit() else date_str
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO schedule_cache(date_str, payload) VALUES (%s::date, %s::jsonb)
                ON CONFLICT (date_str) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
            """, (ds, json.dumps(payload, ensure_ascii=False)))
            conn.commit()
else:
    # DB가 없으면 JSON 파일 캐시 사용
    def get_runtime_cache_entry(key: str):
        return get_runtime_cache().get(key)

    def set_runtime_cache_entry(key: str, runtime_min: int):
        set_runtime_cache(key, runtime_min)

    def get_schedule_cache_for_date_pg(date_str: str):
        return get_schedule_cache().get(date_str)

    def set_schedule_cache_for_date_pg(date_str: str, payload: list):
        set_schedule_cache_for_date(date_str, payload)

# ---------- Selenium 드라이버 ----------
try:
    from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
except Exception:
    ChromeDriverManager = None

def _guess_chrome_path_windows() -> Optional[str]:
    candidates = [
        os.getenv("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None

def make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--window-size=1280,1200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
    )

    if platform.system() == "Windows":
        chrome_path = _guess_chrome_path_windows()
        if chrome_path:
            opts.binary_location = chrome_path
        if os.getenv("HEADLESS", "0") == "1":
            opts.add_argument("--headless=new")
        if ChromeDriverManager is None:
            return webdriver.Chrome(options=opts)
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)

    # Linux/Docker(Railway)
    opts.add_argument("--headless=new")
    opts.binary_location = os.getenv("CHROME_BIN", "/usr/bin/chromium")
    service = Service(os.getenv("CHROMEDRIVER_BIN", "/usr/bin/chromedriver"))
    return webdriver.Chrome(service=service, options=opts)

# ---------- 크롤 유틸 ----------
def get_today_cards(driver):
    wait = WebDriverWait(driver, 20)
    today = datetime.today().strftime("%Y%m%d")
    url = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameDate={today}"
    driver.get(url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    soup = BeautifulSoup(driver.page_source, "html.parser")
    return soup.select("li.game-cont") or soup.select("li[class*='game-cont']")

def extract_match_info_from_card(li):
    home_nm = li.get("home_nm"); away_nm = li.get("away_nm")
    g_id = li.get("g_id"); g_dt = li.get("g_dt")

    if not (home_nm and away_nm):
        h = li.select_one(".team.home .emb img"); a = li.select_one(".team.away .emb img")
        if a and not away_nm: away_nm = a.get("alt","").strip() or None
        if h and not home_nm: home_nm = h.get("alt","").strip() or None

    if not (home_nm and away_nm):
        txt = li.get_text(" ", strip=True)
        m = re.search(r"([A-Za-z가-힣]+)\s*vs\s*([A-Za-z가-힣]+)", txt, re.I)
        if m:
            away_nm = away_nm or m.group(1)
            home_nm = home_nm or m.group(2)

    if not (g_id and g_dt):
        a = li.select_one("a[href*='GameCenter/Main.aspx'][href*='gameId='][href*='gameDate=']")
        if a and a.has_attr("href"):
            href = a["href"]
            mg = re.search(r"gameId=([A-Z0-9]+)", href)
            md = re.search(r"gameDate=(\d{8})", href)
            if mg: g_id = g_id or mg.group(1)
            if md: g_dt = g_dt or md.group(1)

    return {"home": home_nm, "away": away_nm, "g_id": g_id, "g_dt": g_dt}

def find_today_matches_for_team(driver, my_team: str):
    results = []
    for li in get_today_cards(driver):
        info = extract_match_info_from_card(li)
        if not (info["home"] and info["away"]):
            continue
        if my_team in {info["home"], info["away"]}:
            info["rival"] = info["home"] if info["away"] == my_team else info["away"]
            results.append(info)
    return results

def get_games_for_date(driver, date_str: str):
    cached = get_schedule_cache_for_date_pg(date_str)
    if cached is not None:
        return cached

    wait = WebDriverWait(driver, 15)
    url = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameDate={date_str}"
    driver.get(url)
    try:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        set_schedule_cache_for_date_pg(date_str, [])
        return []

    soup = BeautifulSoup(driver.page_source, "html.parser")
    games_min = []
    for li in soup.select("li.game-cont") or soup.select("li[class*='game-cont']"):
        info = extract_match_info_from_card(li)
        if all([info.get("home"), info.get("away"), info.get("g_id"), info.get("g_dt")]):
            games_min.append({k: info[k] for k in ("home","away","g_id","g_dt")})
    set_schedule_cache_for_date_pg(date_str, games_min)
    return games_min

def open_review_and_get_runtime(driver, game_id: str, game_date: str) -> Optional[int]:
    today_str = datetime.today().strftime("%Y%m%d")
    use_cache = (game_date != today_str)
    key = make_runtime_key(game_id, game_date)

    if use_cache:
        hit = get_runtime_cache_entry(key)
        if hit and "runtime_min" in hit:
            return hit["runtime_min"]

    base = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameId={game_id}&gameDate={game_date}"
    driver.get(base); time.sleep(0.8)
    clicked = False
    try:
        WebDriverWait(driver, 4).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), '리뷰')]"))
        ).click()
        clicked = True; time.sleep(0.8)
    except Exception:
        pass
    if not clicked:
        driver.get(base + "&section=REVIEW"); time.sleep(0.8)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    run_min = None
    span = soup.select_one("div.record-etc span#txtRunTime")
    if span:
        m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", span.get_text(strip=True))
        if m:
            run_min = int(m.group(1))*60 + int(m.group(2))

    if use_cache and run_min is not None:
        set_runtime_cache_entry(key, run_min)
    return run_min

def collect_history_avg_runtime(my_team: str, rival_set: Optional[Set[str]] = None) -> Tuple[Optional[float], List[int]]:
    driver = None
    try:
        driver = make_driver()
    except Exception:
        return (None, [])

    try:
        end_dt = datetime.today() - timedelta(days=1)
        start_dt = end_dt - timedelta(days=MAX_LOOKBACK_DAYS)
        date_list = [d.strftime("%Y%m%d") for d in pd.date_range(start=start_dt, end=end_dt)]

        times: List[int] = []
        for d in date_list:
            for info in get_games_for_date(driver, d):
                if my_team in {info["home"], info["away"]}:
                    opp = info["home"] if info["away"] == my_team else info["away"]
                    if (not rival_set) or (opp in rival_set):
                        try:
                            rt = open_review_and_get_runtime(driver, info["g_id"], info["g_dt"])
                        except Exception:
                            rt = None
                        if rt is not None:
                            times.append(rt)
        return (round(sum(times)/len(times), 1), times) if times else (None, [])
    finally:
        try:
            if driver: driver.quit()
        except Exception:
            pass

# ---------- Flask 블루프린트 ----------
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
hour_bp = Blueprint("hour_alt", __name__, template_folder=TEMPLATE_DIR)

@hour_bp.route("/hour/ping")
def hour_ping():
    return "pong", 200

@hour_bp.route("/hour", methods=["GET", "POST"])
@hour_bp.route("/hour/", methods=["GET", "POST"])
def hour_index():
    result = None; avg_time = None; css_class = ""; msg = ""; selected_team = None

    # GET과 POST 모두 지원 (iframe/프록시에서 POST 막힘 대비)
    team = request.args.get("team") if request.method == "GET" else request.form.get("myteam")
    if team:
        selected_team = team
        MY_TEAM = team

        # 빠른 드라이버 점검
        try:
            _tmp = make_driver(); _tmp.quit()
        except Exception:
            return render_template(
                HOUR_TEMPLATE,
                result=f"{MY_TEAM} 평균 시간 계산 불가",
                avg_time=None, css_class="",
                msg="드라이버 실행 실패: Linux 컨테이너의 chromium/chromedriver 경로 확인.",
                selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70
            )

        # 오늘 상대 확인(실패해도 진행)
        try:
            d = make_driver()
            today_matches = find_today_matches_for_team(d, MY_TEAM)
            d.quit()
        except Exception:
            today_matches = []

        if today_matches:
            rivals_today = {m["rival"] for m in today_matches if m.get("rival")}
            result = f"오늘 {MY_TEAM}의 상대팀은 {', '.join(rivals_today)}입니다."
            try:
                avg_time, _ = collect_history_avg_runtime(MY_TEAM, rivals_today)
            except Exception:
                avg_time = None; msg = "평균 계산 중 오류(드라이버/네트워크)"
            if avg_time is None and not msg:
                msg = "과거 경기 데이터가 없습니다."
        else:
            result = f"{MY_TEAM}의 오늘 경기는 없습니다. (최근 {MAX_LOOKBACK_DAYS}일 기준)"
            try:
                avg_time, _ = collect_history_avg_runtime(MY_TEAM, rival_set=None)
            except Exception:
                avg_time = None; msg = "평균 계산 중 오류(드라이버/네트워크)"
            if avg_time is None and not msg:
                msg = "과거 경기 데이터가 없습니다."

        if avg_time is not None:
            if      avg_time < TOP30:    css_class, msg = "fast", "빠르게 끝나는 경기입니다"
            elif    avg_time < AVG_REF:  css_class, msg = "normal", "일반적인 경기 소요 시간입니다"
            elif    avg_time < BOTTOM70: css_class, msg = "bit-long", "조금 긴 편이에요"
            else:                         css_class, msg = "long", "시간 오래 걸리는 매치업입니다"

    try:
        return render_template(
            HOUR_TEMPLATE,
            result=result, avg_time=avg_time, css_class=css_class, msg=msg,
            selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70
        )
    except TemplateNotFound:
        return "<div>템플릿이 없습니다.</div>", 200

# ---------- 단독 실행 ----------
def create_app():
    app = Flask(__name__)
    app.register_blueprint(hour_bp)
    return app

if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5002, debug=True, use_reloader=False)
