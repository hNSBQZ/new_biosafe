ARG PYTHON_BASE_IMAGE=python:3.12-slim
ARG NODE_BASE_IMAGE=node:22-alpine

FROM ${NODE_BASE_IMAGE} AS web-builder

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /build

COPY web/package.json web/package-lock.json ./
RUN npm ci --registry="${NPM_REGISTRY}"

COPY web/ ./
RUN npm run build

FROM ${PYTHON_BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    BIOSAFE_ENV=production \
    BIOSAFE_DATABASE_PATH=/app/data/biosafe.db \
    BIOSAFE_EXPERIMENTS_DIR=/app/experiments \
    BIOSAFE_WEB_DIST_PATH=/app/web/dist \
    BIOSAFE_LOG_FILE=/app/logs/biosafe-api.log

WORKDIR /app

RUN groupadd --system --gid 10001 biosafe \
    && useradd --system --uid 10001 --gid biosafe --home-dir /app --shell /usr/sbin/nologin biosafe

COPY pyproject.toml ./
COPY biosafe ./biosafe
COPY services ./services
COPY scripts ./scripts
COPY experiments ./experiments
COPY --from=web-builder /build/dist ./web/dist

RUN python -m pip install --no-cache-dir . \
    && mkdir -p /app/data /app/logs \
    && chown -R biosafe:biosafe /app

USER biosafe

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"

STOPSIGNAL SIGTERM

CMD ["uvicorn", "services.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
