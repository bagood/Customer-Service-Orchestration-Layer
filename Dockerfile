FROM ghcr.io/astral-sh/uv:0.11.16 AS uv
FROM python:3.12-slim
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
COPY app app
COPY global global
COPY workflow workflow
USER 65534:65534
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
