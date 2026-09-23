FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY frontend/requirements.txt /app/requirements.txt
RUN uv pip install --system -r /app/requirements.txt
RUN uv pip install --system mkdocs-material "mkdocstrings[python]"

COPY . /app

# Compilation de la documentation MkDocs dans frontend/site
RUN mkdocs build -d /app/frontend/site

WORKDIR /app/frontend

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:9000/login || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:9000", "--workers", "3", "--timeout", "30", "--graceful-timeout", "10", "frontend:app"]
