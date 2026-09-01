FROM python:3.12-alpine

WORKDIR /app

# Copier et installer les dépendances (Flask et Uvicorn)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9000

CMD ["uvicorn", "frontend:app", "--host", "0.0.0.0", "--port", "9000"]
