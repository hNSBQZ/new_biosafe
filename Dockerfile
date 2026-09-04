FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system --gid 10001 biosafe \
    && useradd --system --uid 10001 --gid biosafe --home-dir /app --shell /usr/sbin/nologin biosafe

COPY pyproject.toml ./
COPY biosafe ./biosafe
COPY services ./services
COPY scripts ./scripts
COPY experiments ./experiments

RUN python -m pip install --no-cache-dir \
        --index-url https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com \
        . \
    && mkdir -p /app/data /app/logs \
    && chown -R biosafe:biosafe /app

USER biosafe

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"

STOPSIGNAL SIGTERM

CMD ["uvicorn", "services.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
