FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

# Variables d'opti UV
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

#  dépendances requises par Camoufox
RUN playwright install-deps firefox \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /tmp/* /var/tmp/* /root/.cache /root/.uv

# Téléchargement du binaire Camoufox
RUN python -m camoufox fetch
COPY . .
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
