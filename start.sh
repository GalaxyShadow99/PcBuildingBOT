#!/usr/bin/env bash
set -e

# Se placer dans le dossier du projet
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "Lancement de PcBuildingBOT..."
echo "=========================================="

# 1. Vérification du fichier d'environnement .env
if [ ! -f .env ]; then
    if [ -f .env.prod ]; then
        echo "Fichier .env introuvable. Copie de .env.prod vers .env..."
        cp .env.prod .env
    else
        echo "Erreur : Fichier .env ou .env.prod introuvable."
        exit 1
    fi
fi

# 2. Construction et démarrage des conteneurs
echo "Build et démarrage des conteneurs Docker..."
docker compose up -d --build

# 3. Affichage de l'état des conteneurs
echo ""
echo "État des conteneurs :"
docker compose ps

echo ""
echo "=========================================="
echo "PcBuildingBOT est démarré !"
echo "Dashboard Web (Frontend) : http://localhost:9000"
echo "API Backend (FastAPI)     : http://localhost:8000"
echo ""
echo "Pour suivre les logs en direct :"
echo "   docker compose logs -f"
echo "=========================================="
