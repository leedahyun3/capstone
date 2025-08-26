# shorts_alt.py
from __future__ import annotations

import os
import platform
import time
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

def _make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1024")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-infobars")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
    )

    if platform.system() == "Windows":
        # 로컬 윈도우: 설치된 Chrome 사용(셀레니움 매니저 자동)
        return webdriver.Chrome(options=opts)

    # Linux/Railway: Dockerfile에서 설치된 바이너리 경로 사용
    opts.binary_location = os.getenv("CHROME_BIN", "/usr/bin/chromium")
    service = Service(os.getenv("CHROMEDRIVER_BIN", "/usr/bin/chromedriver"))
    return webdriver.Chrome(service=service, options=opts)

def fetch_kbo_shorts_alt(max_items: int = 30) -> List[Dict[str, str]]:
    driver = _make_driver()
    try:
        url = "https://m.sports.naver.com/kbaseball/index"
        driver.get(url)
        time.sleep(3)  # 간단 대기

        shorts: List[Dict[str, str]] = []
        cards = driver.find_elements(By.CSS_SELECTOR, 'a[data-event-area^="keyword"]')
        for card in cards[:max_items]:
            # 제목
            try:
                title = card.find_element(By.CSS_SELECTOR, "span.sds-comps-text-ellipsis-1").text.strip()
            except Exception:
                title = ""
            # 요약
            try:
                summary = card.find_element(By.CSS_SELECTOR, "span.sds-comps-ellipsis-content").text.strip()
                if title and summary and (summary == title or summary.startswith(title)):
                    summary = ""
            except Exception:
                summary = ""
            # 링크/이미지/시간
            link = card.get_attribute("href") or ""
            try:
                image = card.find_element(By.TAG_NAME, "img").get_attribute("src") or ""
            except Exception:
                image = ""
            try:
                time_str = card.find_element(By.CSS_SELECTOR, "span.fds-shortents-compact-date").text.strip()
            except Exception:
                time_str = ""

            if title or link:
                shorts.append({"title": title, "summary": summary, "link": link, "image": image, "time": time_str})
        return shorts
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    for i, it in enumerate(fetch_kbo_shorts_alt(), 1):
        print(f"{i}. {it['title']}  | {it['link']}")
