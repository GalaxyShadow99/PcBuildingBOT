# PcBuildingBOT

**PcBuildingBOT** est un bot automatisé hyper léger développé en Python (FastAPI + Flask + Httpx) pour surveiller en temps réel les annonces d'occasion (**Vinted**). Il recherche des composants informatiques définis par l'utilisateur sous un prix plafond, applique un filtrage IA via Ollama/LLM et des filtres intelligents anti-panne/anti-accessoires, puis envoie des notifications directement sur **Discord**.

---

## Fonctionnalités

- **Scraping Léger & Rapide :** Surveillance ultra-rapide de Vinted via des requêtes HTTP asynchrones (Httpx), sans aucun navigateur lourd.
- **Filtrage IA Ollama / LLM :** Analyse intelligente des annonces pour éliminer les faux-positifs, boîtes vides et modèles non correspondants.
- **API Rest & Dashboard Web :** Interface Flask moderne en Bootstrap 5 pour gérer la liste de surveillance, basculer le statut des recherches et visualiser les annonces.
- **Système Anti-Spam & Cooldown 403 :** Détection des bannissements IP avec mise en pause automatique de 30 minutes et gestion native des Rate Limits Discord (429).
- **Nettoyage automatique du salon Discord :** Purge automatique des anciens messages Discord (limite configurable à 25 messages) et purge lors de la suppression d'une recherche.
- **Filtrage Intelligent Heuristique :** Détection automatique du matériel HS/pour pièces, des boîtes vides (multi-langues), et exclusion des accessoires hors-sujet (ventirads hollandais/allemands `koeler`/`kühler`, etc.).
- **Docker** : un simple `docker-compose up -d --build` et c'est en ligne.

---

## Architecture 

```text
PcBuildingBOT/
├── backend/               # API FastAPI, scraper Vinted Httpx & base SQLite
│   ├── scrapers/          # Scraper Vinted ultra-léger (Httpx)
│   ├── services/          # Analyse IA Ollama (ai_analyzer.py)
│   ├── database.py        # Gestion SQLite & migrations
│   ├── main.py            # Serveur API FastAPI & boucle de scan
│   └── Dockerfile
|
|── test/                  # Jeu de test pour l'API et le front end à lancer via `pytest -v` 
|
├── frontend/              # Application Web Flask & Templates Bootstrap 5
│   ├── frontend.py        # Routes Flask et consommateur API
│   ├── templates/         # Vues HTML (Navbar, Watchlist, Modals, Erreurs 404/500)
│   └── Dockerfile
├── docker-compose.yml     # Orchestration des conteneurs Backend + Frontend
├── .env.prod
├── .env.dev               # Modèle des variables d'environnement
└── README.md
```

---

## Installation & Déploiement

### 1. Configuration des variables d'environnement

Copiez le fichier exemple `.env.prod` pour créer votre fichier `.env` :

```bash
cp .env.prod .env
```

Éditez le fichier `.env` pour y renseigner votre Webhook Discord et vos clés secrètes :

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/VOTRE_WEBHOOK
API_SECRET_KEY=votre_cle_api_secrete
FLASK_SECRET_KEY=votre_cle_flask_secrete
UI_USERNAME=admin
UI_PASSWORD=votre_mot_de_passe
OLLAMA_HOST=http://host.docker.internal:11434
OLLAMA_MODEL=gemma:2b
```

---

### 2. Lancement Docker Compose

```bash
docker-compose up -d --build
```

L'application sera accessible sur :
- **Dashboard Web (Frontend) :** `http://localhost:9000`
- **API Backend (FastAPI) :** `http://localhost:8000`

---

### 3. Lancement en Développement Local

#### Backend (FastAPI)
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

#### Frontend (Flask)
```bash
cd frontend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python frontend.py
```

> [!IMPORTANT]
> Ce projet utilise des appels d'API sur un serveur local d'IA 'llama-server', afin d'éviter les faux positifs 
> que les filtres textuels ne pourraont pas bloquer, les gens sont trop imprévisible sur leurs annonces pour être 
> bloqué suffisamment efficacement avec des  filtres textuels  ! 

> [!WARNING]
> Vous devrez donc configurer VOUS MEME ce serveur IA et renseigner les variables d'environnement du .env 
> Pour ma part ce projet tournera en production avec un qwen2.5 3B sur une Quadro P400


---

Projet par Thomas .C