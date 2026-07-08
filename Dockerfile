FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHROMIUM_BINARY=/usr/bin/chromium \
    CHROMIUM_HEADLESS=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        curl \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        procps \
        xauth \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt
RUN python - <<'PY'
import importlib

for module_name in ("scrapling", "scrapling.fetchers", "curl_cffi", "playwright", "patchright"):
    importlib.import_module(module_name)

print("Scrapling runtime check passed.")
PY

COPY . .
RUN mkdir -p /app/data

EXPOSE 7777

CMD ["sh", "-lc", "xvfb-run -a --server-args='-screen 0 1920x1080x24' python app.py"]
