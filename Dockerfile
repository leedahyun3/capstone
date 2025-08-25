FROM python:3.10-slim

# 로케일/폰트/타임존(옵션)
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=Asia/Seoul

# Chromium & chromedriver & 한글 폰트 + 필요한 런타임 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-noto-cjk \
    # ── chrome headless 필수 런타임들 (권장)
    libnss3 libgconf-2-4 libxi6 libxrender1 libxcomposite1 \
    libxrandr2 libatk1.0-0 libatk-bridge2.0-0 libxdamage1 \
    libgbm1 libasound2 libpangocairo-1.0-0 \
  && rm -rf /var/lib/apt/lists/*

# 런타임 환경변수
ENV PYTHONUNBUFFERED=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver \
    PORT=8000

WORKDIR /app

# 파이썬 패키지
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스
COPY . .

# ── 엔트리포인트:
# 선택 A: team_ranking_back_alt가 메인인 경우(블루프린트 등록을 코드에서 수행)
CMD ["/bin/sh","-c","gunicorn team_ranking_back_alt:app -b 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 180"]

# 선택 B: app.py 통합 엔트리포인트 사용 시 아래로 교체
# CMD ["/bin/sh","-c","gunicorn app:app -b 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 180"]
