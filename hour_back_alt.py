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
        info =

