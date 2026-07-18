FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5006 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

WORKDIR /app

# deps de sistema (curl + libs do chromium)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates wget gnupg \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
      fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

# baixa o chromium fora do home do user pra evitar problemas de permissão
RUN mkdir -p $PLAYWRIGHT_BROWSERS_PATH && playwright install chromium

COPY . .

RUN useradd -u 10001 -m appuser \
    && mkdir -p /data \
    && chown -R appuser /app /data $PLAYWRIGHT_BROWSERS_PATH
USER appuser

EXPOSE 5006

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/health || exit 1

CMD ["gunicorn", "-c", "gunicorn_conf.py", "app:app"]
