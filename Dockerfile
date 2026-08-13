FROM node:22-bookworm-slim AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YTSAGE_HOST=0.0.0.0 \
    YTSAGE_PORT=8080 \
    YTSAGE_CONFIG_DIR=/config \
    YTSAGE_DOWNLOAD_DIR=/downloads \
    YTSAGE_QUEUE_CONCURRENCY=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY ytsage ./ytsage
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --from=ui /app/frontend/dist ./ytsage/server/static
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 ytsage \
    && mkdir -p /config /downloads \
    && chown -R ytsage:ytsage /config /downloads /app \
    && chmod 0755 /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8080
VOLUME ["/config", "/downloads"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["ytsage"]
