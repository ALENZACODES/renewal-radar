# One container serves the API and the frontend. Used locally and on Render.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Tesseract lets the "Load sample scan" path and scanned uploads work.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
COPY fixtures ./fixtures
COPY data ./data
COPY docs ./docs
ENV PYTHONPATH=/app/backend \
    DATABASE_URL=sqlite:////tmp/renewal_radar.db \
    PORT=8000 \
    RR_PUBLISHED_BOARD_URL=https://raw.githubusercontent.com/ALENZACODES/renewal-radar/rates-data/published_board.json
EXPOSE 8000
# One worker keeps memory well under 512 MB. Proxy headers give the rate limiter the real client address.
CMD ["sh", "-c", "exec uvicorn renewal.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
