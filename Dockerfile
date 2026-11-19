FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    CSOL_DB_PATH=/app/data/csol.sqlite3
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 csol \
    && useradd --uid 10001 --gid csol --no-create-home csol \
    && mkdir /app/data && chown csol:csol /app/data
COPY src ./src
COPY configs ./configs
COPY scripts ./scripts

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import http.client; c = http.client.HTTPConnection('127.0.0.1', 8000, timeout=2); c.request('GET', '/mcp'); assert c.getresponse().status == 401"
CMD ["python", "-m", "csol.server"]
