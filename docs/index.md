# PcBuildingBOT - Documentation Technique

## Presentation du projet

PcBuildingBOT est une application de scrapping Vinted pour surveiller automatisée et en temps réel d'annonces de composants informatiques d'occasion sur  Vinted.

L'application combine un filtrage matériel (exclusions croisées, chipsets, générations de mémoire RAM) et une validation décisionnelle par modèle de langage (LLM via Ollama / llama-server) afin d'éliminer les faux-positifs et d'envoyer des notifications sur Discord.

---

## Architecture Globale

- **Backend (FastAPI)** : Service d'API REST asynchrone assurant le scraping Vinted via `httpx`, le filtrage multi-niveaux, l'analyse LLM et la persistance SQLite.
- **Frontend (Flask + Gunicorn)** : Interface utilisateur en Bootstrap 5 permettant de gérer la liste de surveillance, consulter les annonces notifiées et visualiser la santé du service.
- **Base de donnees (SQLite)** : Stockage persistant.
- **Service IA (llama-server / Ollama)** : Inférence LLM locale valider la pertinence des annonces via schema Pydantic JSON.

---

## Pipeline de Filtrage en 5 Niveaux

1. **Exclusion Materiel Defectueux / HS** : Analyse lexicale multilingue du titre et de la description pour exclure les annonces pour pièces ou en panne.
2. **Banwords categorises et specifiques** : Dictionnaire global de mots bannis (`default_banned_words`) combine aux mots bannis definis par recherche.
3. **Detection des Emballages et Boites Vides** : Analyse d'exclusion pour repérer les cartons et boîtes seules sans composant.
4. **Validation Determinte Materielle** : Contrôle strict de compatibilité des chipsets de cartes mères (B85 vs H610), des générations de RAM (DDR3 vs DDR4 vs DDR5) et des formats SODIMM vs DIMM.
5. **Validation Decisionnelle LLM** : Validation binaire de l'opportunite d'achat (`is_good_deal`) via JSON Schema Pydantic.
