FROM python:3.12-slim

WORKDIR /app

# Installation de curl, puis nettoyage immédiat du cache APT
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Installation des dépendances Python via pip classique (sans cache pour gagner de la place)
RUN pip install --no-cache-dir -r requirements.txt

# Installation des paquets système de Firefox + Nettoyage du cache APT
RUN playwright install-deps firefox \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Télécharger le binaire Firefox personnalisé anti-détection de Camoufox
RUN python -m camoufox fetch

COPY . .

# Dossier de stockage pour la base de données
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
