# Customer-Agent 生产镜像（需 X11 / xvfb 才能运行 PyQt6 UI）
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    QT_QPA_PLATFORM=offscreen

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    xvfb \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libx11-6 \
    libxext6 \
    libxcb1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && uv run playwright install --with-deps chromium

COPY . .

RUN mkdir -p /app/data /app/logs /app/backup /app/temp

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -sf http://127.0.0.1:8080/health || exit 1

CMD ["sh", "-c", "uv run python -m alembic -c alembic.ini upgrade head 2>/dev/null || true; exec xvfb-run -a uv run python app.py"]
