FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HAYSTACK_TELEMETRY_ENABLED=false

WORKDIR /app

COPY pyproject.toml README.md ./
COPY radar_intelligence ./radar_intelligence
RUN python -m pip install --no-cache-dir ".[haystack]" \
    && adduser --disabled-password --gecos "" --uid 10001 intelligence \
    && mkdir -p /var/lib/radar-intelligence \
    && chown -R intelligence:intelligence /app /var/lib/radar-intelligence

USER intelligence
EXPOSE 8081

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=3).read()"

CMD ["python", "-m", "radar_intelligence.api"]
