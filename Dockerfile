FROM python:3.10-slim

# 로케일 및 폰트
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

# Chromium & chromedriver & 한글 폰트 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    fonts-noto-cjk \
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

# 앱 실행 (Render/Railway가 PORT를 주입)
CMD ["/bin/sh","-c","gunicorn team_ranking_back_alt:app -b 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 180"]
