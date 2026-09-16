#!/usr/bin/env bash
set -e

# Se placer dans le dossier du projet
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "Arrêt de PcBuildingBOT..."
echo "=========================================="

# Arrêt et suppression des conteneurs Docker
docker compose down

echo ""
echo "=========================================="
echo "PcBuildingBOT est arrêté."
echo "=========================================="
