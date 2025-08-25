# hour_back_alt.py
# - "평균 경기시간" 기능을 독립 실행도 되고, 다른 Flask 앱에 블루프린트로도 붙일 수 있게 구성
# - 템플릿 파일은 templates/hour_alt.html 을 사용

from flask import Flask, Blueprint, request, render_template
import time, os, json, re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

# ===================== 설정/상수 =====================
# 기준값 (분)
TOP30 = 168
AVG_REF = 182.7
BOTTOM70 = 194
START_DATE = "2025-03-22"

# 캐시 파일(JSON, 최소 필드만 저장)
RUNTIME_CACHE_FILE = "runtime_cache.json"     # key: "{game_id}_{game_date}" -> {"runtime_min": int}
SCHEDULE_CACHE_FILE = "schedule_index.json"   # key: "YYYYMMDD" -> [ {"home","away","g_id","g_dt"} ]

# ===================== 유틸: JSON 로드/세이브 =====================
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

def get_runtime_cache():
    return _load_json(RUNTIME_CACHE_FILE, {})

def set_runtime_cache(key, runtime_min):
    cache = get_runtime_cache()
    cache[key] = {"runtime_min": runtime_min}  # 필요한 것만 저장
    _save_json(RUNTIME_CACHE_FILE, cache)

def get_schedule_cache():
    return _load_json(SCHEDULE_CACHE_FILE, {})

def set_schedule_cache_for_date(date_str, games_minimal_list):
    cache = get_schedule_cache()
    cache[date_str] = games_minimal_list  # 필요한 것만 저장
    _save_json(SCHEDULE_CACHE_FILE, cache)

def make_runtime_key(game_id: str, game_date: str) -> str:
    return f"{game_id}_{game_date}"

def delete_all_caches():
    for p in [RUNTIME_CACHE_FILE, SCHEDULE_CACHE_FILE]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

# ===================== Selenium 드라이버 =====================
def make_driver():
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,1200")
    # 필요 시 UA 추가
    # options.add_argument("user-agent=Mozilla/5.0 ...")
    return webdriver.Chrome(options=options)

# ===================== 스케줄/경기카드 파싱 =====================
def get_today_cards(driver):
    wait = WebDriverWait(driver, 10)
    today = datetime.today().strftime("%Y%m%d")
    url = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameDate={today}"
    driver.get(url)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    soup = BeautifulSoup(driver.page_source, "html.parser")
    cards = soup.select("li.game-cont") or soup.select("li[class*='game-cont']")
    return cards

def extract_match_info_from_card(card_li):
    # 신형/구형 DOM 모두 커버
    home_nm = card_li.get("home_nm")
    away_nm = card_li.get("away_nm")
    g_id = card_li.get("g_id")
    g_dt = card_li.get("g_dt")

    # 이미지 alt 백업
    if not (home_nm and away_nm):
        home_alt = card_li.select_one(".team.home .emb img")
        away_alt = card_li.select_one(".team.away .emb img")
        if away_alt and not away_nm:
            away_nm = away_alt.get("alt", "").strip() or None
        if home_alt and not home_nm:
            home_nm = home_alt.get("alt", "").strip() or None

    # 텍스트 백업: "... A vs B ..." 패턴
    if not (home_nm and away_nm):
        txt = card_li.get_text(" ", strip=True)
        m = re.search(r"([A-Za-z가-힣]+)\s*vs\s*([A-Za-z가-힣]+)", txt, re.I)
        if m:
            a, b = m.group(1), m.group(2)
            away_nm = away_nm or a
            home_nm = home_nm or b

    # 상세 링크에서 파라미터 추출 백업
    if not (g_id and g_dt):
        a = card_li.select_one("a[href*='GameCenter/Main.aspx'][href*='gameId='][href*='gameDate=']")
        if a and a.has_attr("href"):
            href = a["href"]
            gm = re.search(r"gameId=([A-Z0-9]+)", href)
            dm = re.search(r"gameDate=(\d{8})", href)
            if gm:
                g_id = g_id or gm.group(1)
            if dm:
                g_dt = g_dt or dm.group(1)

    return {
        "home": home_nm,
        "away": away_nm,
        "g_id": g_id,
        "g_dt": g_dt,
    }

def find_today_matches_for_team(driver, my_team):
    cards = get_today_cards(driver)
    results = []
    for li in cards:
        info = extract_match_info_from_card(li)
        home, away = info["home"], info["away"]
        if not (home and away):
            continue
        if my_team in {home, away}:
            rival = home if away == my_team else away
            info["rival"] = rival
            results.append(info)
    return results

# 날짜별 스케줄(최소필드) 캐시
def get_games_for_date(driver, date_str):
    """
    반환: [ {"home","away","g_id","g_dt"} ... ]
    """
    cache = get_schedule_cache()
    if date_str in cache:
        return cache[date_str]

    wait = WebDriverWait(driver, 10)
    url = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameDate={date_str}"
    driver.get(url)
    try:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except:
        set_schedule_cache_for_date(date_str, [])
        return []

    soup = BeautifulSoup(driver.page_source, "html.parser")
    cards = soup.select("li.game-cont") or soup.select("li[class*='game-cont']")
    games_minimal = []
    for li in cards:
        info = extract_match_info_from_card(li)
        if all([info.get("home"), info.get("away"), info.get("g_id"), info.get("g_dt")]):
            games_minimal.append({
                "home": info["home"],
                "away": info["away"],
                "g_id": info["g_id"],
                "g_dt": info["g_dt"],
            })

    set_schedule_cache_for_date(date_str, games_minimal)
    return games_minimal

# ===================== 리뷰 탭에서 런타임(분) 추출 =====================
def open_review_and_get_runtime(driver, game_id, game_date):
    """
    리뷰 탭에서 경기 소요 시간(분)을 파싱.
    - 오늘 날짜(game_date == today)는 캐시 무시 (진행 중 가능성)
    """
    today_str = datetime.today().strftime("%Y%m%d")
    use_cache = (game_date != today_str)
    key = make_runtime_key(game_id, game_date)

    # 캐시 조회
    if use_cache:
        rc = get_runtime_cache()
        hit = rc.get(key)
        if hit and isinstance(hit, dict) and "runtime_min" in hit:
            return hit["runtime_min"]

    # 실제 크롤링
    base = f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameId={game_id}&gameDate={game_date}"
    driver.get(base)
    time.sleep(1.5)
    clicked = False
    try:
        review_tab = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), '리뷰')]"))
        )
        review_tab.click()
        clicked = True
        time.sleep(1.5)
    except Exception:
        clicked = False
    if not clicked:
        driver.get(base + "&section=REVIEW")
        time.sleep(1.2)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    run_time_min = None
    record_etc = soup.select_one("div.record-etc")
    if record_etc:
        span = record_etc.select_one("span#txtRunTime")
        if span:
            runtime = span.get_text(strip=True)
            m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", runtime)
            if m:
                h, mnt = int(m.group(1)), int(m.group(2))
                run_time_min = h * 60 + mnt

    # 캐시에 저장
    if use_cache and run_time_min is not None:
        set_runtime_cache(key, run_time_min)

    return run_time_min

# ===================== 과거 평균 런타임 집계 =====================
def collect_history_avg_runtime(my_team, rival_set, start_date=START_DATE):
    """
    - 오늘 제외 (미완성 데이터 차단)
    - 게임별 런타임은 open_review_and_get_runtime에서 캐시됨 (runtime_min만 저장)
    - 날짜별 스케줄도 최소필드만 캐시
    """
    driver = make_driver()

    # 오늘 제외
    today_minus_1 = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")
    date_list = [d.strftime("%Y%m%d") for d in pd.date_range(start=start_date, end=today_minus_1)]

    run_times = []
    for date in date_list:
        games = get_games_for_date(driver, date)
        if not games:
            continue
        for info in games:
            home, away, game_id, game_date = info["home"], info["away"], info["g_id"], info["g_dt"]
            if my_team in {home, away}:
                opponent = home if away == my_team else away
                if opponent not in rival_set:
                    continue
                try:
                    rt = open_review_and_get_runtime(driver, game_id, game_date)
                except Exception:
                    rt = None
                if rt is not None:
                    run_times.append(rt)

    driver.quit()

    if run_times:
        avg_time = round(sum(run_times) / len(run_times), 1)
        return avg_time, run_times
    else:
        return None, []

# ===================== 블루프린트 & 앱 팩토리 =====================
hour_bp = Blueprint("hour_alt", __name__, template_folder="templates")

@hour_bp.route("/hour", methods=["GET", "POST"])
def hour_index():
    result = None
    avg_time = None
    css_class = ""
    msg = ""
    selected_team = None

    if request.method == "POST":
        MY_TEAM = request.form.get("myteam")
        selected_team = MY_TEAM
        if not MY_TEAM:
            result = "팀을 선택해주세요."
            return render_template(
                "hour_alt.html",
                result=result, avg_time=avg_time, css_class=css_class, msg=msg,
                selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70
            )

        # 오늘 경기의 상대팀 찾기
        driver = make_driver()
        today_matches = find_today_matches_for_team(driver, MY_TEAM)
        driver.quit()

        if not today_matches:
            result = f"{MY_TEAM}의 오늘 경기를 찾지 못했습니다."
            return render_template(
                "hour_alt.html",
                result=result, avg_time=avg_time, css_class=css_class, msg=msg,
                selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70
            )

        rivals_today = {m["rival"] for m in today_matches if m.get("rival")}
        rivals_str = ", ".join(rivals_today)
        result = f"오늘 {MY_TEAM}의 상대팀은 {rivals_str}입니다."

        # 과거 평균 경기시간 계산 (오늘 제외)
        avg_time, _ = collect_history_avg_runtime(MY_TEAM, rivals_today)

        if avg_time is not None:
            if avg_time < TOP30:
                css_class, msg = "fast", "빠르게 끝나는 경기입니다"
            elif avg_time < AVG_REF:
                css_class, msg = "normal", "일반적인 경기 소요 시간입니다"
            elif avg_time < BOTTOM70:
                css_class, msg = "bit-long", "조금 긴 편이에요"
            else:
                css_class, msg = "long", "시간 오래 걸리는 매치업입니다"
            result = f"오늘 {MY_TEAM}의 상대팀은 {rivals_str}입니다.<br>과거 {MY_TEAM} vs {rivals_str} 평균 경기시간: {avg_time}분"
        else:
            result = f"오늘 {MY_TEAM}의 상대팀은 {rivals_str}입니다.<br>과거 경기 데이터가 없습니다."

    return render_template(
        "hour_alt.html",
        result=result, avg_time=avg_time, css_class=css_class, msg=msg,
        selected_team=selected_team, top30=TOP30, avg_ref=AVG_REF, bottom70=BOTTOM70
    )

def create_app():
    app = Flask(__name__)
    app.register_blueprint(hour_bp)
    return app

# 독립 실행 지원 (테스트/개발용)
if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5002, use_reloader=False)
