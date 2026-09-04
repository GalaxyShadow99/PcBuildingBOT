import os
import sys

from dotenv import load_dotenv
from logger import logger
from ollama import AsyncClient
from pydantic import BaseModel

load_dotenv()

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "")

if not OLLAMA_HOST:
    logger.fatal("OLLAMA_HOST doit être défini. Valeur actuelle : %s", OLLAMA_HOST)
    sys.exit(1)

# Assure le préfixe http:// ou https:// et le port 11434
if not OLLAMA_HOST.startswith("http://") and not OLLAMA_HOST.startswith("https://"):
    OLLAMA_HOST = f"http://{OLLAMA_HOST}"

if ":11434" not in OLLAMA_HOST and OLLAMA_HOST.count(":") < 2:
    OLLAMA_HOST = f"{OLLAMA_HOST}:11434"

if not OLLAMA_MODEL:
    logger.fatal("OLLAMA_MODEL doit être défini. Valeur actuelle : %s", OLLAMA_MODEL)
    sys.exit(1)


class OllamaReponse(BaseModel):
    verdict: str
    state_and_traps: str
    short_advice: str
    summary: str
    score: float


async def analyzeDealWithOllama(title: str, price: float, maxPrice: float, keywords: str, description: str = None) -> tuple[str, float]:
    """
    Envoie les détails de l'annonce à Ollama (Qwen 2.5 7B) via le SDK officiel (AsyncClient)
    avec réponse structurée Pydantic pour analyser si c'est une vraie bonne affaire.
    """
    prompt = f"""Tu es un expert hardware PC impitoyable et logique, spécialisé dans le dénichage de composant informatique d'occasion (Carte mère, GPU/Carte graphique, RAM, Processeur/CPU, SSD, Alimentation, Ventirad/AIO, Boîtier).

RÈGLE ABSOLUE N°1 : N'ÉVOQUE JAMAIS LES PHOTOS OU VISUELS (tu n'analyses que le texte).

RÈGLE ABSOLUE N°2 : ÉVALUATION DES PRIX ET BUDGET :
- L'acheteur a fixé un Prix Max Référence de {maxPrice} € pour {keywords}.
- Si le produit est un vrai composant PC valide (ex: Carte mère H610) ET que le Prix Proposé ({price} €) est inférieur ou égal au Prix Max ({maxPrice} €), C'EST UNE BONNE AFFAIRE ! Donne une note OBLIGATOIREMENT >= 14.0/20.
- Plus le prix ({price} €) est bas par rapport au budget max ({maxPrice} €), plus la note DOIT être élevée (ex: 16/20 à 18/20). Ne dis JAMAIS que c'est "trop cher" si le prix est sous le budget max !

RÈGLE ABSOLUE N°3 : PRODUITS HORS-SUJET :
- Si l'annonce est un objet sans rapport avec les composants PC fixes (ex: Tablette graphique, jeu vidéo, housse, stylet) -> Attribue IMMÉDIATEMENT la note 0.0/20 et indiques "Produit Hors-Sujet (Tablette graphique)" dans le verdict.

DONNÉES ANNONCE :
- Recherche initiale : {keywords}
- Titre annonce : {title}
- Prix proposé : {price} € (Budget Max configuré : {maxPrice} €)
- Description vendeur : {description if description else "Aucune description"}

BARÈME DE NOTATION (note float de 0.0 à 20.0) :
- 16.0 à 20.0 /20 : Vrai composant PC à prix très avantageux (très inférieur à {maxPrice} €).
- 12.0 à 15.0 /20 : Vrai composant PC à prix correct ({price} € <= {maxPrice} €).
- 0.0 à 11.9 /20 : Produit hors-sujet (tablette graphique), matériel cassé/HS, ou prix supérieur au budget max ({price} € > {maxPrice} €).

CHAMPS À REMPLIR :
1. verdict : "Super Affaire", "Prix Correct", "Trop Cher" ou "Hors-Sujet / Piège".
2. state_and_traps : Résume l'état et pièges (ex: composant fixe OK, SODIMM laptop, ou hors-sujet).
3. short_advice : Conseil d'achat direct et concis (ex: "Excellente affaire pour carte mère H610").
4. summary : Synthèse exacte des données (Modèle, Marque, Prix).
5. score : Note float de 0.0 à 20.0 selon les règles ci-dessus.
"""

    try:
        client = AsyncClient(host=OLLAMA_HOST, timeout=60.0)
        response = await client.chat(
            model=OLLAMA_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format=OllamaReponse.model_json_schema()
        )
        
        raw_content = response.message.content
        parsed = OllamaReponse.model_validate_json(raw_content)
        logger.info("[Ollama Analysis OK] Score: %s/20 | Verdict: %s", parsed.score, parsed.verdict)
        
        # Mise en forme lisible pour l'embed Discord
        formatted_analysis = (
            f"**Note :** {parsed.score}/20\n"
            f"**Verdict :** {parsed.verdict}\n"
            f"**État & Pièges :** {parsed.state_and_traps}\n"
            f"**Conseil :** {parsed.short_advice}\n"
            f"**Résumé :** {parsed.summary}"
        )
        return formatted_analysis, float(parsed.score)

    except Exception as e:
        logger.warning("⚠️ Impossible d'analyser l'annonce avec Ollama sur %s : %s", OLLAMA_HOST, e)
        return None, None
