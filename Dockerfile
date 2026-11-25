FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 gps \
    && useradd --uid 10001 --gid 10001 --create-home gps \
    && install -d -m 0700 -o gps -g gps /app/instance
COPY gps ./gps
COPY migrations ./migrations
COPY data ./data
COPY docs/openapi.yaml ./docs/openapi.yaml
COPY manage.py .

USER 10001:10001
VOLUME ["/app/instance"]
EXPOSE 5050

HEALTHCHECK --interval=15s --timeout=4s --start-period=15s --retries=4 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/health', timeout=3).close()"]
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5050", "gps.app:create_app()"]
