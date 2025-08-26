FROM python:3.10-slim

# 로케일/폰트/타임존
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=Asia/Seoul

# Chromium & chromedriver & 한글 폰트 + 필요한 런타임 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-noto-cjk \
    # headless chromium이 필요로 하는 런타임 (Debian bookworm 호환)
    libnss3 libxi6 libxrender1 libxcomposite1 \
    libxrandr2 libatk1.0-0 libatk-bridge2.0-0 libxdamage1 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    libxshmfence1 libx11-xcb1 libdrm2 libxfixes3 \
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

# 엔트리포인트 (A 선택: team_ranking_back_alt가 메인)
CMD ["sh","-c","gunicorn app_combined:app -b 0.0.0.0:${PORT:-8000} --workers 1 --threads 2 --timeout 300 --log-level info"]

