import os
import sys

from dotenv import load_dotenv
from logger import logger
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

# Par défaut sur llama-server, le port est 8080 (ou configuré via --port)
LLAMA_HOST = os.environ.get("LLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://host.docker.internal:8080"

if not LLAMA_HOST.startswith("http://") and not LLAMA_HOST.startswith("https://"):
    LLAMA_HOST = f"http://{LLAMA_HOST}"

# Client compatible OpenAI ciblant llama-server
client = AsyncOpenAI(
    base_url=f"{LLAMA_HOST}/v1",
    api_key="no-key-required",
    timeout=120.0
)


class DealResponse(BaseModel):
    """Schéma Pydantic de réponse JSON de l'analyseur LLM."""
    is_good_deal: bool
    reason: str
    short_advice: str


async def analyzeDealWithLlama(title: str, price: float, maxPrice: float, keywords: str, description: str = None) -> tuple[str, bool]:
    """
    Envoie les détails de l'annonce à llama-server via l'API OpenAI avec 
    réponse structurée Pydantic binaire (is_good_deal: bool).
    Le prompt est assoupli pour la RAM et reste strict pour les autres composants.
    """
    kw_lower = keywords.lower()
    is_ram_search = any(ram_term in kw_lower for ram_term in ["ram", "ddr", "ddr4", "ddr5", "sodimm", "8go", "16go", "32go"])

    if is_ram_search:
        has_sodimm_kw = any(term in kw_lower for term in ["sodimm", "so-dimm", "portable", "laptop", "notebook"])
        sodimm_rule = "Format SODIMM/portable autorisé." if has_sodimm_kw else "REJETTE (`is_good_deal = false`) si la RAM est au format SODIMM / PC portable / Laptop car la recherche est pour PC fixe."

        prompt = f"""Tu es un assistant de filtrage de mémoire vive (RAM) d'occasion.

RECHERCHE : {keywords}
TITRE : {title}
DESCRIPTION : {description if description else "Aucune"}

RÈGLES DÉCISION :
1. Valide l'annonce -> `is_good_deal = true` si c'est une RAM fonctionnelle correspondant au type recherché.
2. REJETTE (`is_good_deal = false`) si :
   - C'est de la DDR3 alors que la recherche est DDR4 (ou vice versa).
   - {sodimm_rule}
   - Matériel défectueux, HS ou boîte vide.

EXEMPLE VALIDE :
Recherche: "16 Go DDR4" | Titre: "Barrette RAM Corsair 16Go DDR4 3200MHz" -> `is_good_deal = true`

EXEMPLE REJETÉ :
Recherche: "16 Go DDR4" | Titre: "Barrette RAM Sodimm DDR3 4Go Portable" -> `is_good_deal = false`

Sois très concis (1 phrase max par champ).
"""
    else:
        if any(gpu_term in kw_lower for gpu_term in ["rtx", "gtx", "rx", "gpu", "carte graphique", "graphics card"]):
            prompt = f"""Tu es un assistant de validation de cartes graphiques (GPU) d'occasion.

RECHERCHE : {keywords}
TITRE : {title}
DESCRIPTION : {description if description else "Aucune"}

RÈGLES DÉCISION :
1. VALIDE (`is_good_deal = true`) toute vraie carte graphique équipée du processeur graphique recherché (ex: RTX 3080).
   ATTENTION : Les marques et modèles des constructeurs (ex: Gainward Phoenix, EVGA FTW3, MSI Ventus, Gigabyte Gaming OC, Asus TUF, Zotac) SONT 100% VALIDES si la puce GPU correspond !
2. REJETTE (`is_good_deal = false`) uniquement si :
   - C'est seulement une boîte vide, un ventirad seul ou une backplate sans la carte graphique.
   - C'est un GPU totalement différent (ex: RTX 3060 alors que la recherche est RTX 3080).
   - Le composant est HS ou en panne.

EXEMPLE VALIDE :
Recherche: "RTX 3080" | Titre: "Gainward GeForce RTX 3080 Phoenix 10GB" -> `is_good_deal = true` (Raison: C'est bien une RTX 3080 de marque Gainward)

EXEMPLE REJETÉ :
Recherche: "RTX 3080" | Titre: "Boîte seule RTX 3080 sans carte" -> `is_good_deal = false`

Sois très concis (1 phrase max par champ).
"""
        elif any(cpu_term in kw_lower for cpu_term in ["i3", "i5", "i7", "i9", "ryzen", "cpu", "processeur"]):
            prompt = f"""Tu es un assistant de validation de processeurs (CPU) d'occasion.

RECHERCHE : {keywords}
TITRE : {title}
DESCRIPTION : {description if description else "Aucune"}

RÈGLES DÉCISION :
1. VALIDE (`is_good_deal = true`) uniquement si l'annonce propose EXACTEMENT le modèle et la génération de processeur recherchés (ex: i3 12100 pour i3 12100, Ryzen 5 5600 pour Ryzen 5 5600).
2. REJETTE (`is_good_deal = false`) impérativement si :
   - C'est un modèle de génération ou référence différente (ex: i3-8100, i3-9100 ou i3-10100F alors que la recherche est i3 12100, ou Ryzen 3600 alors que la recherche est Ryzen 5600).
   - C'est une gamme différente (ex: i5 au lieu de i3, ou Ryzen 7 au lieu de Ryzen 5).
   - C'est seulement un ventirad/refroidisseur seul (ex: Wraith Stealth, cooler), une boîte vide sans processeur, ou un processeur HS/défectueux.

EXEMPLE VALIDE :
Recherche: "i3 12100" | Description: "Processeur Intel Core i3 12100F socket LGA1700" -> `is_good_deal = true` (Raison: Modèle exact i3 12100)

EXEMPLE REJETÉ :
Recherche: "i3 12100" | Description: "Processeur Intel Core i3 8100" -> `is_good_deal = false` (Raison: Génération 8100 différente de 12100 recherché)

Sois très concis (1 phrase max par champ).
"""
        else:
            prompt = f"""Tu es un assistant de filtrage de composants PC d'occasion.

RECHERCHE : {keywords}
TITRE : {title}
DESCRIPTION : {description if description else "Aucune"}

RÈGLES DÉCISION :
1. VALIDE (`is_good_deal = true`) si l'annonce propose le composant informatique recherché en état fonctionnel.
2. REJETTE (`is_good_deal = false`) si l'annonce est hors-sujet, un accessoire sans rapport, un matériel HS ou une boîte vide.

Sois très concis (1 phrase max par champ).
"""

    try:
        response = await client.chat.completions.create(
            model="local-model",
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "DealResponse",
                    "strict": True,
                    "schema": DealResponse.model_json_schema()
                }
            },
            max_tokens=1024
        )
        
        raw_content = response.choices[0].message.content
        if not raw_content:
            logger.warning("Réponse vide reçue de llama-server.")
            return None, None

        try:
            parsed = DealResponse.model_validate_json(raw_content)
        except Exception as val_err:
            import json
            import re
            logger.warning("Échec du parsing Pydantic direct, tentative de récupération du JSON : %s", val_err)
            match = re.search(r'\{.*\}', raw_content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                parsed = DealResponse(
                    is_good_deal=bool(data.get("is_good_deal", False)),
                    reason=str(data.get("reason", "Analyse automatique")),
                    short_advice=str(data.get("short_advice", "Vérifier l'annonce"))
                )
            else:
                raise val_err

        logger.debug("[Llama Analysis OK] Valide: %s | Raison: %s", parsed.is_good_deal, parsed.reason)
        
        status_icon = "Bonne affaire" if parsed.is_good_deal else "À éviter"
        formatted_analysis = (
            f"**Statut :** {status_icon}\n"
            f"**Analyse :** {parsed.reason}\n"
            f"**Conseil :** {parsed.short_advice}"
        )
        return formatted_analysis, parsed.is_good_deal

    except Exception as e:
        logger.warning("⚠️ Impossible d'analyser l'annonce avec llama-server sur %s : [%s]", LLAMA_HOST, type(e).__name__)
        return None, None


# Alias pour rétrocompatibilité
analyzeDealWithOllama = analyzeDealWithLlama