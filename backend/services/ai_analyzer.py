import os
import sys

from dotenv import load_dotenv
from logger import logger
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

# Par défaut sur llama-server, le port est 8080 (ou configuré via --port)
LLAMA_HOST = os.environ.get("LLAMA_HOST", "http://localhost:8080")

if not LLAMA_HOST.startswith("http://") and not LLAMA_HOST.startswith("https://"):
    LLAMA_HOST = f"http://{LLAMA_HOST}"

# Client compatible OpenAI ciblant llama-server
# api_key est requise par le SDK OpenAI mais llama-server n'en a pas besoin par défaut
client = AsyncOpenAI(
    base_url=f"{LLAMA_HOST}/v1",
    api_key="no-key-required",
    timeout=120.0
)


class DealResponse(BaseModel):
    is_good_deal: bool
    reason: str
    short_advice: str


async def analyzeDealWithLlama(title: str, price: float, maxPrice: float, keywords: str, description: str = None) -> tuple[str, bool]:
    """
    Envoie les détails de l'annonce à llama-server via l'API OpenAI avec 
    contrainte de grammaire JSON via Pydantic.
    """
    kw_lower = keywords.lower()
    
    if any(gpu_term in kw_lower for gpu_term in ["rtx", "gtx", "rx", "gpu", "carte graphique", "graphics card"]):
        specific_rules = """
EXIGENCES CARTE GRAPHIQUE (GPU) :
1. Toute vraie carte graphique équipée de la puce recherchée (ex: RTX 2060, peu importe la marque Asus, MSI, Gigabyte, Zotac, Palit, EVGA, etc.) EST 100% VALIDE -> `is_good_deal = true`.
2. Si l'annonce ne vend QUE le ventirad, le refroidisseur, la backplate ou la boîte vide ("box only", "boite vide", "caja vacia") sans la carte graphique physique -> REJET (`is_good_deal = false`).
"""
    elif any(ram_term in kw_lower for ram_term in ["ram", "ddr", "ddr4", "ddr5", "sodimm", "8go", "16go", "32go"]):
        specific_rules = f"""
EXIGENCES MÉMOIRE VIVE (RAM) :
1. CAPACITÉ RÉELLE : La capacité totale vendue doit correspondre à la recherche "{keywords}". Si l'annonce vend moins de capacité (ex: 4Go au lieu de 16Go) -> REJET (`is_good_deal = false`).
2. FIXE VS PORTABLE : Si la recherche est pour PC Fixe et que l'annonce vend du PC Portable / SODIMM / Laptop -> REJET (`is_good_deal = false`).
"""
    else:
        specific_rules = """
EXIGENCES GÉNÉRALES COMPOSANTS PC :
1. L'annonce doit proposer une vraie pièce informatique fonctionnelle et cohérente avec la recherche.
2. Si c'est un accessoire sans rapport, un meuble, un jeu ou un objet hors-sujet -> REJET (`is_good_deal = false`).
"""

    prompt = f"""Tu es un assistant de filtrage hardware d'occasion.
Ton UNIQUE rôle est de vérifier si l'annonce correspond exactement au composant PC recherché.

DONNÉES ANNONCE À ANALYSER :
- Composant recherché : {keywords}
- Titre annonce : {title}
- Description : {description if description else "Aucune"}

=====================================================
EXEMPLES DE DÉCISIONS À SUIVRE (FEW-SHOT) :
=====================================================

--- EXEMPLE 1 (VALIDE - Boîte non originale) ---
Recherche : "Ryzen 5 3600"
Titre : "Processeur AMD Ryzen 5 3600"
Description : "Processeur en très bon état. La boîte n'est pas celle d'origine. Le processeur fonctionne très bien."
-> Décision : `is_good_deal = true` (Raison: Le processeur Ryzen 5 3600 est vendu fonctionnel, peu importe le carton d'emballage)

--- EXEMPLE 2 (VALIDE - Annonce en italien/espagnol) ---
Recherche : "Ryzen 5 3600"
Titre : "Cpu Amd ryzen 5 3600"
Description : "Cpu perfettamente funzionante, perfette condizioni e pronta all'uso!"
-> Décision : `is_good_deal = true` (Raison: C'est le processeur Ryzen 5 3600 exact en parfait état)

--- EXEMPLE 3 (REJETÉ - Boîte vide) ---
Recherche : "RTX 2060"
Titre : "Boite vide RTX 2060"
Description : "Seulement la boîte en carton sans la carte graphique."
-> Décision : `is_good_deal = false` (Raison: Boîte vide sans composant)

--- EXEMPLE 4 (REJETÉ - Modèle différent) ---
Recherche : "GTX 1660"
Titre : "Carte graphique GTX 1660 Super"
Description : "Vend carte graphique 1660 Super 6Go"
-> Décision : `is_good_deal = false` (Raison: GTX 1660 Super n'est pas la GTX 1660 exacte)

=====================================================
RÈGLES STRICTES :
=====================================================
1. Si le composant exact est présent et fonctionnel -> `is_good_deal = true` (MÊME si la boîte n'est pas originale ou si la description est en italien/espagnol).
2. Si le modèle varie (ex: Super, Ti au lieu de la recherche de base), si c'est une boîte vide ou du matériel HS -> `is_good_deal = false`.
{specific_rules}
"""

    try:
        response = await client.chat.completions.create(
            # llama-server charge déjà le modèle en mémoire, ce champ est indicatif
            model="local-model",
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2,
            # Force la sortie JSON stricte respectant le schéma Pydantic via la grammaire de llama.cpp
            response_format={
                "type": "json_object",
                "schema": DealResponse.model_json_schema()
            },
            max_tokens=256
        )
        
        raw_content = response.choices[0].message.content
        parsed = DealResponse.model_validate_json(raw_content)
        logger.info("[Llama Analysis OK] Valide: %s | Raison: %s", parsed.is_good_deal, parsed.reason)
        
        status_icon = "Bonne affaire" if parsed.is_good_deal else "À éviter"
        formatted_analysis = (
            f"**Statut :** {status_icon}\n"
            f"**Analyse :** {parsed.reason}\n"
            f"**Conseil :** {parsed.short_advice}"
        )
        return formatted_analysis, parsed.is_good_deal

    except Exception as e:
        logger.warning("⚠️ Impossible d'analyser l'annonce avec llama-server sur %s : [%s] %s", LLAMA_HOST, type(e).__name__, e or repr(e))
        return None, None