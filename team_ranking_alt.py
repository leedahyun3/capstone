# team_ranking_alt.py
# Cross-platform Chrome WebDriver setup:
# - Windows (local dev): uses webdriver-manager to auto-install matching chromedriver
# - Linux/Docker (Render/Railway): uses CHROME_BIN/CHROMEDRIVER_BIN paths (see Dockerfile)

from __future__ import annotations

import os
import time
from typing import List, Dict

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# webdriver-manager is optional (used on Windows local)
try:
    from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
except Exception:  # pragma: no cover
    ChromeDriverManager = None  # will error at runtime on Windows if missing


def make_driver() -> webdriver.Chrome:
    """Create a headless Chrome driver that works on both Windows and Linux/Docker."""
    opts = Options()
    # Headless & stability flags
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1024")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
    )

    if os.name == "nt":
        # Windows: use webdriver-manager to auto-install a matching chromedriver
        if ChromeDriverManager is None:
            raise RuntimeError(
                "webdriver-manager not installed. Run: pip install webdriver-manager"
            )
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)

    # Linux/Docker: use binaries provided by the image (see Dockerfile)
    chrome_bin = os.getenv("CHROME_BIN", "/usr/bin/chromium")
    driver_bin = os.getenv("CHROMEDRIVER_BIN", "/usr/bin/chromedriver")
    opts.binary_location = chrome_bin
    service = Service(driver_bin)
    return webdriver.Chrome(service=service, options=opts)


def fetch_team_rankings() -> List[Dict[str, str]]:
    """Fetch KBO team rankings from Naver (mobile) and return as a list of dicts."""
    driver = make_driver()
    url = "https://m.sports.naver.com/kbaseball/record/index"
    driver.get(url)

    try:
        # Wait until the list container appears
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ol.TableBody_list__P8yRn"))
        )
        # And at least one item is present
        WebDriverWait(driver, 40).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.TableBody_item__eCenH"))
        )
        # Tiny buffer for late text rendering
        time.sleep(1.0)
    except TimeoutException:
        with open("debug.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.quit()
        raise

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    table = soup.select_one("ol.TableBody_list__P8yRn")
    if not table:
        # Save snapshot for debugging if structure changes
        with open("debug.html", "w", encoding="utf-8") as f:
            f.write(str(soup)[:200000])
        return []

    team_list = table.select("li.TableBody_item__eCenH")
    data: List[Dict[str, str]] = []

    for team in team_list:
        cells = team.select("div.TableBody_cell__rFrpm")
        if len(cells) < 6:
            continue

        team_info = cells[0]
        team_name_el = team_info.select_one(".TeamInfo_team_name__dni7F")
        rank_el = team_info.select_one(".TeamInfo_ranking__MqHpq")
        logo_img = team_info.select_one(".TeamInfo_emblem__5JUAY img")
        logo_url = logo_img["src"] if logo_img and logo_img.has_attr("src") else ""

        def get_stat(cell) -> str:
            blind = cell.select_one("span.blind")
            if blind and blind.next_sibling:
                return str(blind.next_sibling).strip()
            return cell.get_text(strip=True)

        team_name = team_name_el.get_text(strip=True) if team_name_el else ""
        rank = (rank_el.get_text(strip=True) if rank_el else "").replace("위", "")

        gb = get_stat(cells[2])
        wins = get_stat(cells[3])
        draws = get_stat(cells[4])
        losses = get_stat(cells[5])

        data.append(
            {
                "rank": rank,
                "team_name": team_name,
                "logo": logo_url,
                "gb": gb,
                "wins": wins,
                "draws": draws,
                "losses": losses,
            }
        )

    return data


if __name__ == "__main__":
    # Quick local test
    for row in fetch_team_rankings():
        print(row)
