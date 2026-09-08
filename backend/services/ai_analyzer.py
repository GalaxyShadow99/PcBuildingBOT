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
    is_good_deal: bool
    reason: str
    short_advice: str


async def analyzeDealWithOllama(title: str, price: float, maxPrice: float, keywords: str, description: str = None) -> tuple[str, bool]:
    """
    Envoie les détails de l'annonce à Ollama via le SDK officiel (AsyncClient) avec réponse
    structurée Pydantic binaire (is_good_deal: bool) adaptée aux modèles 3B.
    """
    kw_lower = keywords.lower()
    
    # Construction dynamique des instructions spécifiques pour éviter d'embrouiller le modèle 3B
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
Ton UNIQUE rôle est de vérifier si l'annonce correspond au composant PC recherché et qu'il ne s'agit pas d'une arnaque/piège.
Remarque : Le prix ({price} €) est DÉJÀ validé par le système. Ne compare PAS le prix.

DONNÉES ANNONCE :
- Composant recherché : {keywords}
- Titre annonce : {title}
- Description : {description if description else "Aucune"}

=====================================================
RÈGLES STRICTES À APPLIQUER :
=====================================================
1. Le produit doit être un composant informatique PC fonctionnel. Si le matériel est cassé / HS / pour pièces / non testé -> REJET (`is_good_deal = false`).
{specific_rules}

=====================================================
DÉCISION FINALE :
=====================================================
Si l'annonce est valide et correspond au composant recherché -> `is_good_deal = true`.
Si l'annonce est un piège (boîte seule, RAM 4Go au lieu de 16Go, SODIMM, matériel HS, produit hors-sujet) -> `is_good_deal = false`.

Indique la raison exacte dans `reason` et un conseil concis dans `short_advice`. Ne parle jamais d'images ou de photos.
"""

    try:
        client = AsyncClient(host=OLLAMA_HOST, timeout=120.0)
        response = await client.chat(
            model=OLLAMA_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format=OllamaReponse.model_json_schema(),
            options={
                "temperature": 0.3,
                "num_ctx": 4096,
                "num_gpu": 99
            }
        )
        
        raw_content = response.message.content
        parsed = OllamaReponse.model_validate_json(raw_content)
        logger.info("[Ollama Analysis OK] Valide: %s | Raison: %s", parsed.is_good_deal, parsed.reason)
        
        status_icon = "Bonne affaire" if parsed.is_good_deal else "À éviter"
        formatted_analysis = (
            f"**Statut :** {status_icon}\n"
            f"**Analyse :** {parsed.reason}\n"
            f"**Conseil :** {parsed.short_advice}"
        )
        return formatted_analysis, parsed.is_good_deal

    except Exception as e:
        logger.warning("⚠️ Impossible d'analyser l'annonce avec Ollama sur %s : [%s] %s", OLLAMA_HOST, type(e).__name__, e or repr(e))
        return None, None
