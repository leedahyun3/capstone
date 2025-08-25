# hour_back_alt.py
from flask import Flask, Blueprint, request, render_template
from jinja2 import TemplateNotFound
import os, json, re, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

# ===== 기준/캐시 =====
TOP30 = 168
AVG_REF = 182.7
BOTTOM70 = 194
START_DATE = "2025-03-22"

RUNTIME_CACHE_FILE = "runtime_cache.json"     # "{game_id}_{game_date}" -> {"runtime_min": int}
SCHEDULE_CACHE_FILE = "schedule_index.json"   # "YYYYMMDD" -> [ {"home","away","g_id","g_dt"} ]

def _load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def get_runtime_cache(): return _load_json(RUNTIME_CACHE_FILE, {})
def set_runtime_cache(key, runtime_min):
    cache = get_runtime_cache()
    cache[key] = {"runtime_min": runtime_min}
    _save_json(RUNTIME_CACHE_FILE, cache)

def get_schedule_cache(): return _load_json(SCHEDULE_CACHE_FILE, {})
def set_schedule_cache_for_date(date_str, games_minimal_list):
    cache = get_schedule_cache()
    cache[date_str] = games_minimal_list
    _save_json(SCHEDULE_CACHE_FILE, cache)

def make_runtime_key(game_id, game_date): return f"{game_id}_{game_date}"

# ===== Selenium =====
def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,1200")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
    return webdriver.Chrome(options=opts)

# ===== 크롤 유틸 =====
def get_today_cards(driver):
    wait = WebDriverWait(driver, 10)
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
        if a and not away_nm: away_nm = a.get("alt", "").strip() or None
        if h and not home_nm: home_nm = h.get("alt", "").strip() or None

    if not (home_nm and away_nm):
        txt = li.get_text(" ", strip=True)
        m = re.search(r"([A-Za-z가-힣]+)\s*vs\s*([A-Za-z가-힣]+)", txt, re.I)
        if m: away_nm = away_nm or m.group(1); home_nm = home_nm or m.group(2)

    if not (g_id and g_dt):
        a = li.select_one("a[href*='GameCenter/Main.aspx'][href*='gameId='][href*='gameDate=']")
        if a and a.has_attr("href"):
            href = a["href"]
            mg = re.search(r"gameId=([A-Z0-9]+)", href)
            md = re.search(r"gameDate=(\d{8})", href)
            if mg: g_id = g_id or mg.group(1)
            if md: g_dt = g_dt or md.group(1)

    return {"home": home_nm, "away": away_nm, "g_id": g_id, "g_dt": g_dt}

def find_today_matches_for_team(driver, my_team):
    results = []
    for li in get_today_cards(driver):
        info = extract_match_info_from_card(li)
        if not (info["home"] and info["away"]): continue
        if my_team in {info["home"], info["away"]}:
            info["rival"] = info["home"] if info["away"] == my_team else info["away"]
            results.append(info)
    return results

def get_games_for_date(driver, date_str):
    cache = get_schedule_cache()
    if date_str in cache: return cache[date_str]

    wait = WebDriverWait(driver, 10)
    url = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameDate={date_str}"
    driver.get(url)
    try: wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except:
        set_schedule_cache_for_date(date_str, []); return []

    soup = BeautifulSoup(driver.page_source, "html.parser")
    games_min = []
    for li in soup.select("li.game-cont") or soup.select("li[class*='game-cont']"):
        info = extract_match_info_from_card(li)
        if all([info.get("home"), info.get("away"), info.get("g_id"), info.get("g_dt")]):
            games_min.append({k: info[k] for k in ("home","away","g_id","g_dt")})
    set_schedule_cache_for_date(date_str, games_min)
    return games_min

def open_review_and_get_runtime(driver, game_id, game_date):
    today_str = datetime.today().strftime("%Y%m%d")
    use_cache = (game_date != today_str)
    key = make_runtime_key(game_id, game_date)

    if use_cache:
        hit = get_runtime_cache().get(key)
        if hit and "runtime_min" in hit: return hit["runtime_min"]

    base = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameId={game_id}&gameDate={game_date}"
    driver.get(base); time.sleep(1.0)
    clicked = False
    try:
        WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), '리뷰')]"))
        ).click()
        clicked = True; time.sleep(1.0)
    except Exception:
        clicked = False
    if not clicked:
        driver.get(base + "&section=REVIEW"); time.sleep(0.8)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    run_min = None
    span = soup.select_one("div.record-etc span#txtRunTime")
    if span:
        m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", span.get_text(strip=True))
        if m: run_min = int(m.group(1))*60 + int(m.group(2))
    if use_cache and run_min is not None: set_runtime_cache(key, run_min)
    return run_min

def collect_history_avg_runtime(my_team, rival_set, start_date=START_DATE):
    driver = make_driver()
    today_minus_1 = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")
    date_list = [d.strftime("%Y%m%d") for d in pd.date_range(start=start_date, end=today_minus_1)]
    times = []
    for d in date_list:
        for info in get_games_for_date(driver, d):
            if my_team in {info["home"], info["away"]}:
                opp = info["home"] if info["away"] == my_team else info["away"]
                if opp in rival_set:
                    try: rt = open_review_and_get_runtime(driver, info["g_id"], info["g_dt"])
                    except Exception: rt = None
                    if rt is not None: times.append(rt)
    driver.quit()
    return (round(sum(times)/len(times),1), times) if times else (None, [])

# ===== 블루프린트 (두 경로 모두 매핑) =====
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
hour_bp = Blueprint("hour_alt", __name__, template_folder=TEMPLATE_DIR)

@hour_bp.route("/hour/ping")
def hour_ping():
    return "pong", 200

@hour_bp.route("/hour", methods=["GET", "POST"])
@hour_bp.route("/hour/", methods=["GET", "POST"])
def hour_index():
    result = None; avg_time = None; css_class = ""; msg = ""; selected_team = None

    if request.method == "POST":
        MY_TEAM = request.form.get("myteam"); selected_team = MY_TEAM
        if not MY_TEAM:
            try:
                return render_template("hour_alt.html", result="팀을 선택해주세요.", avg_time=None, css_class="", msg="",
                                       selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70)
            except TemplateNotFound:
                return "<div>hour_alt.html 템플릿이 없습니다.</div>", 200

        driver = make_driver()
        today_matches = find_today_matches_for_team(driver, MY_TEAM)
        driver.quit()

        if not today_matches:
            try:
                return render_template("hour_alt.html",
                                       result=f"{MY_TEAM}의 오늘 경기를 찾지 못했습니다.",
                                       avg_time=None, css_class="", msg="",
                                       selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70)
            except TemplateNotFound:
                return f"<div>{MY_TEAM}의 오늘 경기를 찾지 못했습니다.</div>", 200

        rivals_today = {m["rival"] for m in today_matches if m.get("rival")}
        result = f"오늘 {MY_TEAM}의 상대팀은 {', '.join(rivals_today)}입니다."
        avg_time, _ = collect_history_avg_runtime(MY_TEAM, rivals_today)

        if avg_time is not None:
            if      avg_time < TOP30:   css_class, msg = "fast", "빠르게 끝나는 경기입니다"
            elif    avg_time < AVG_REF: css_class, msg = "normal", "일반적인 경기 소요 시간입니다"
            elif    avg_time < BOTTOM70:css_class, msg = "bit-long", "조금 긴 편이에요"
            else:                        css_class, msg = "long", "시간 오래 걸리는 매치업입니다"
            result += f"<br>과거 {MY_TEAM} vs {', '.join(rivals_today)} 평균 경기시간: {avg_time}분"
        else:
            result += "<br>과거 경기 데이터가 없습니다."

    try:
        return render_template("hour_alt.html",
                               result=result, avg_time=avg_time, css_class=css_class, msg=msg,
                               selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70)
    except TemplateNotFound:
        return "<div>hour_alt.html 템플릿이 없습니다.</div>", 200

def create_app():
    app = Flask(__name__)
    app.register_blueprint(hour_bp)
    return app

if __name__ == "__main__":
    create_app().run(debug=True, port=5002, use_reloader=False)
