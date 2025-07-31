from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

def fetch_kbo_shorts():
    options = Options()
    options.add_argument('--headless')  # 디버깅 시 주석처리
    options.add_argument('--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1')
    driver = webdriver.Chrome(options=options)
    url = "https://m.sports.naver.com/kbaseball/index"
    driver.get(url)
    time.sleep(3)

    shorts = []
    # 숏츠 카드: a[data-event-area^="keyword"]
    cards = driver.find_elements(By.CSS_SELECTOR, 'a[data-event-area^="keyword"]')
    for card in cards:
        # 제목
        try:
            title = card.find_element(By.CSS_SELECTOR, "span.sds-comps-text-ellipsis-1").text.strip()
        except:
            title = ""
        # 요약(미리보기)
        try:
            summary = card.find_element(By.CSS_SELECTOR, "span.sds-comps-ellipsis-content").text.strip()
            if title.strip() and summary.strip():
                if summary.strip() == title.strip() or summary.strip().startswith(title.strip()):
                    summary = ""
        except:
            summary = ""
        # 링크
        link = card.get_attribute("href")
        # 이미지
        try:
            image = card.find_element(By.TAG_NAME, "img").get_attribute("src")
        except:
            image = ""
        # 시간
        try:
            time_str = card.find_element(By.CSS_SELECTOR, "span.fds-shortents-compact-date").text.strip()
        except:
            time_str = ""
        shorts.append({
            "title": title,
            "summary": summary,
            "link": link,
            "image": image,
            "time": time_str
        })
    driver.quit()
    return shorts

if __name__ == "__main__":
    result = fetch_kbo_shorts()
    if not result:
        print("❌ 숏콘텐츠가 없습니다.")
    else:
        for i, item in enumerate(result, 1):
            print(f"{i}. 🎬 제목: {item['title']}\n   🔗 링크: {item['link']}\n   🖼️ 이미지: {item['image']}\n   📝 요약: {item['summary']}\n   🕒 시간: {item['time']}")
            print("-" * 60)

