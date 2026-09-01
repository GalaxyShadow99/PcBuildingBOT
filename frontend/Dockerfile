FROM python:3.12-alpine
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt \
    && rm -rf /root/.cache /root/.uv

COPY . .
EXPOSE 9000

CMD ["uvicorn", "frontend:app", "--host", "0.0.0.0", "--port", "9000"]
