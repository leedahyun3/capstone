# recent.py
from __future__ import annotations

import os
import time
from typing import List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def _make_driver() -> webdriver.Chrome:
    """Railway(리눅스)와 로컬(윈도우/맥) 모두에서 잘 동작하도록 드라이버 생성."""
    opts = Options()
    # 안정화 플래그
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1200")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    # 모바일 UA (네이버 모바일 페이지용)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
    )

    # Railway(리눅스) 환경이면 CHROME_BIN/CHROMEDRIVER_BIN 사용
    chrome_bin = os.getenv("CHROME_BIN")
    chromedriver_bin = os.getenv("CHROMEDRIVER_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin
    if chromedriver_bin:
        service = Service(chromedriver_bin)
        return webdriver.Chrome(service=service, options=opts)
    # 로컬은 기본 경로
    return webdriver.Chrome(options=opts)


def fetch_recent_results(target_team: str) -> List[str]:
    """
    네이버 모바일 KBO 팀 순위 페이지에서 해당 팀의 최근 5경기 결과(승/패/무) 수집.
    """
    driver = _make_driver()
    try:
        url = "https://m.sports.naver.com/kbaseball/record/kbo?seasonCode=2025&tab=teamRank"
        driver.get(url)

        # DOM 로드 대기
        wait = WebDriverWait(driver, 12)
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li[class^='TableBody_item__']")))

        team_items = driver.find_elements(By.CSS_SELECTOR, "li[class^='TableBody_item__']")

        for team in team_items:
            # 팀 이름
            try:
                team_name_elem = team.find_element(By.CSS_SELECTOR, "div[class^='TeamInfo_team_name__']")
                team_name = team_name_elem.text.strip()
            except Exception:
                continue

            if team_name != target_team:
                continue

            # 최근 결과 (승/패/무)
            try:
                result_spans = team.find_elements(By.CSS_SELECTOR, "div.ResultInfo_result__Vd3ZN > span.blind")
                results = [span.text for span in result_spans if span.text in ["승", "패", "무"]][:5]
            except Exception:
                results = []

            # 데이터 없을 때 살짝 재시도(네이버 느릴 때 대비)
            if not results:
                time.sleep(1.2)
                try:
                    result_spans = team.find_elements(By.CSS_SELECTOR, "div.ResultInfo_result__Vd3ZN > span.blind")
                    results = [span.text for span in result_spans if span.text in ["승", "패", "무"]][:5]
                except Exception:
                    results = []
            return results

        return []  # 팀을 못 찾은 경우
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    teams = ["한화", "LG", "롯데", "KIA", "SSG", "KT", "삼성", "NC", "두산", "키움"]
    for t in teams:
        print(f"{t}: {fetch_recent_results(t)}")
