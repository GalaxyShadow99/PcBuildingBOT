import os
import sys

from dotenv import load_dotenv
from logger import logger
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

# Par défaut sur llama-server, le port est 8080 (ou configuré via --port)
LLAMA_HOST = (
    os.environ.get("LLAMA_HOST")
    or os.environ.get("OLLAMA_HOST")
    or "http://host.docker.internal:8080"
)

if not LLAMA_HOST.startswith("http://") and not LLAMA_HOST.startswith("https://"):
    LLAMA_HOST = f"http://{LLAMA_HOST}"

# Client compatible OpenAI ciblant llama-server
client = AsyncOpenAI(
    base_url=f"{LLAMA_HOST}/v1", api_key="no-key-required", timeout=120.0
)


DEAL_RESPONSE_GBNF = r'''
root ::= "{" ws "\"reason\"" ws ":" ws string "," ws "\"short_advice\"" ws ":" ws string "," ws "\"is_good_deal\"" ws ":" ws boolean "}"
boolean ::= "true" | "false"
string ::= "\"" ([^"\\] | "\\" [^\n])* "\""
ws ::= [ \t\n\r]*
'''

class DealResponse(BaseModel):
    """
    Schéma Pydantic avec Chain-of-Thought (reason et short_advice EN PREMIER).
    Force le modèle 3B à réfléchir avant de poser son booléen is_good_deal final.
    """
    reason: str
    short_advice: str
    is_good_deal: bool


def repair_and_parse_deal_json(raw_content: str) -> DealResponse:
    """
    Tente de valider le JSON via Pydantic, et applique des secours par Regex
    si le modèle inclut du markdown ou des guillemets non échappés (ex: 2.5" Samsung).
    """
    import json
    import re

    # 1. Nettoyer les balises Markdown éventuelles (```json ... ```)
    cleaned = re.sub(r"```(?:json)?", "", raw_content, flags=re.IGNORECASE).strip()

    # 2. Tentative via Pydantic / json.loads direct
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            data = json.loads(json_str)
            return DealResponse(
                reason=str(data.get("reason", "Analyse automatique")),
                short_advice=str(data.get("short_advice", "Vérifier l'annonce")),
                is_good_deal=bool(data.get("is_good_deal", False)),
            )
        except Exception:
            pass

    # 3. Extraction par Regex en cas de guillemets mal échappés dans les valeurs texte
    deal_match = re.search(r'"is_good_deal"\s*:\s*(true|false)', cleaned, re.IGNORECASE)
    is_good = deal_match.group(1).lower() == "true" if deal_match else False

    reason_match = re.search(
        r'"reason"\s*:\s*"(.*?)"\s*,\s*"short_advice"', cleaned, re.DOTALL
    )
    if not reason_match:
        reason_match = re.search(r'"reason"\s*:\s*"(.*?)"', cleaned, re.DOTALL)
    reason_text = reason_match.group(1) if reason_match else "Analyse automatique"

    advice_match = re.search(r'"short_advice"\s*:\s*"(.*?)"\s*,\s*"is_good_deal"', cleaned, re.DOTALL)
    if not advice_match:
        advice_match = re.search(r'"short_advice"\s*:\s*"(.*?)"', cleaned, re.DOTALL)
    advice_text = advice_match.group(1) if advice_match else "Vérifier l'annonce"

    return DealResponse(
        reason=reason_text.strip(),
        short_advice=advice_text.strip(),
        is_good_deal=is_good,
    )


async def analyzeDealWithLlama(
    title: str, price: float, maxPrice: float, keywords: str, description: str = None
) -> tuple[str, bool]:
    """
    Envoie les détails de l'annonce à llama-server via l'API OpenAI de manière
    100% stateless (indépendante du contexte précédent) avec réponse structurée JSON.
    Optimisé pour Qwen2.5 3B / LLaMA 3B avec Chain-of-Thought (reason d'abord).
    """
    # Assainissement des guillemets dans les entrées pour éviter de polluer le JSON généré
    safe_title = title.replace('"', "''")
    safe_keywords = keywords.replace('"', "''")
    safe_description = (description or "Aucune").replace('"', "''")

    kw_lower = safe_keywords.lower()
    is_ram_search = any(
        ram_term in kw_lower
        for ram_term in ["ram", "ddr", "ddr4", "ddr5", "sodimm", "8go", "16go", "32go"]
    )
    is_gpu_search = any(
        gpu_term in kw_lower
        for gpu_term in [
            "rtx", "gtx", "rx", "gpu", "carte graphique", "graphics card",
            "6600", "6700", "6800", "6900", "3060", "3070", "3080", "3090",
            "4060", "4070", "4080", "4090"
        ]
    )
    is_cpu_search = any(
        cpu_term in kw_lower
        for cpu_term in [
            "i3", "i5", "i7", "i9", "ryzen", "cpu", "processeur",
            "5500", "5600", "5700", "5800", "12400", "13400", "14400"
        ]
    )

    step1_rule = """STEP 1 - MANDATORY PC HARDWARE CHECK:
First check if the item is actual PC hardware (GPU, CPU, RAM, Motherboard, Storage, PSU, Case).
If it is NOT PC hardware (e.g. dishes/terrine, phone, typewriter, printer/toner, toy/car, clothing, furniture) or off-topic, set `is_good_deal = false` immediately.
Second check if the ad refers to a payment outside the platform, set `is_good_deal = false` and the `reason = "Payement hors plateforme"` 
"""

    if is_ram_search:
        has_sodimm_kw = any(
            term in kw_lower
            for term in ["sodimm", "so-dimm", "portable", "laptop", "notebook"]
        )
        sodimm_rule = (
            "SODIMM/laptop RAM allowed."
            if has_sodimm_kw
            else "Set `is_good_deal = false` if RAM is SODIMM/laptop format because query is for desktop PC."
        )

        user_prompt = f"""Task: Validate second-hand RAM listing.

{step1_rule}

SEARCH QUERY: {safe_keywords}
TITLE: {safe_title}
DESCRIPTION: {safe_description}

STEP 2 - RAM RULES:
1. Set `is_good_deal = true` ONLY if it is functional desktop RAM matching the search query.
2. Set `is_good_deal = false` if:
   - DDR3 when DDR4 requested (or vice versa), or DDR generation missing/unspecified.
   - {sodimm_rule}
   - Defective, broken, or empty box.

EXAMPLES:
SEARCH: "16GB DDR4" | TITLE: "Barrette RAM Corsair 16GB DDR4 3200MHz"
-> {{"reason": "RAM DDR4 pour PC fixe correspondant à la recherche.", "short_advice": "Bonne affaire à vérifier.", "is_good_deal": true}}

SEARCH: "16GB DDR4" | TITLE: "Barrette RAM Sodimm 8GB DDR3 Portable"
-> {{"reason": "RAM au format SODIMM portable et DDR3 au lieu de DDR4.", "short_advice": "À éviter.", "is_good_deal": false}}

SEARCH: "16GB DDR4" | TITLE: "Barrette mémoire PC 16GB sans précision DDR"
-> {{"reason": "Génération DDR non spécifiée dans l'annonce.", "short_advice": "Demander confirmation au vendeur.", "is_good_deal": false}}

Write 'reason' and 'short_advice' in concise French (1 sentence max each).
"""
    elif is_gpu_search:
        user_prompt = f"""Task: Validate second-hand GPU listing.

{step1_rule}

SEARCH QUERY: {safe_keywords}
TITLE: {safe_title}
DESCRIPTION: {safe_description}

STEP 2 - GPU RULES:
1. Set `is_good_deal = true` if the target GPU chip (e.g., RTX 3080, RX 6600) is specified in EITHER the TITLE or the DESCRIPTION.
   NOTE: Manufacturer brand variants (MSI, Gigabyte, EVGA, Asus, Zotac, Sapphire, PowerColor) ARE 100% VALID!
2. Set `is_good_deal = false` if:
   - Empty box, cooler only, bracket/backplate only without the GPU card.
   - Completely different GPU model.
   - Defective or broken GPU.

EXAMPLES:
SEARCH: "RTX 3060" | TITLE: "MSI GeForce RTX 3060 Ventus 2X 12G" | DESCRIPTION: "Aucune"
-> {{"reason": "Carte graphique RTX 3060 valide de marque MSI.", "short_advice": "Bonne affaire à vérifier.", "is_good_deal": true}}

SEARCH: "RTX 3060" | TITLE: "Carte graphique gamer" | DESCRIPTION: "Vends carte Gigabyte RTX 3060 12GB en parfait état"
-> {{"reason": "Modèle RTX 3060 bien précisé dans la description.", "short_advice": "Bonne affaire à vérifier.", "is_good_deal": true}}

SEARCH: "RTX 3060" | TITLE: "Boîte vide RTX 3060 Ti pour collection" | DESCRIPTION: "Boîte seule sans carte"
-> {{"reason": "Emballage vide sans la carte graphique.", "short_advice": "À éviter.", "is_good_deal": false}}

Write 'reason' and 'short_advice' in concise French (1 sentence max each).
"""
    elif is_cpu_search:
        user_prompt = f"""Task: Validate second-hand CPU listing.

{step1_rule}

SEARCH QUERY: {safe_keywords}
TITLE: {safe_title}
DESCRIPTION: {safe_description}

STEP 2 - CPU RULES:
1. Set `is_good_deal = true` ONLY if exact CPU model and generation match (e.g., i3 12100, Ryzen 5 5600).
2. Set `is_good_deal = false` if:
   - Different generation or model reference.
   - Different tier (e.g. i5 for i3, Ryzen 7 for Ryzen 5).
   - Cooler only, empty box, or defective CPU.

EXAMPLES:
SEARCH: "Ryzen 5 5600" | TITLE: "Processeur AMD Ryzen 5 5600 Socket AM4"
-> {{"reason": "Modèle exact Ryzen 5 5600 correspondant à la recherche.", "short_advice": "Bonne affaire à vérifier.", "is_good_deal": true}}

SEARCH: "Ryzen 5 5600" | TITLE: "Processeur AMD Ryzen 5 3600"
-> {{"reason": "Génération Ryzen 3600 différente du 5600 recherché.", "short_advice": "À éviter.", "is_good_deal": false}}

SEARCH: "Ryzen 5 5600" | TITLE: "Ventirad d'origine AMD Wraith Stealth"
-> {{"reason": "Refroidisseur seul sans le processeur.", "short_advice": "À éviter.", "is_good_deal": false}}

Write 'reason' and 'short_advice' in concise French (1 sentence max each).
"""
    else:
        user_prompt = f"""Task: Validate second-hand PC component listing.

{step1_rule}

SEARCH QUERY: {safe_keywords}
TITLE: {safe_title}
DESCRIPTION: {safe_description}

STEP 2 - GENERAL RULES:
1. Set `is_good_deal = true` ONLY if it is the target PC component in working condition.
2. Set `is_good_deal = false` if off-topic, unrelated accessory, non-PC item, defective, or empty box.

EXAMPLES:
SEARCH: "6600" | TITLE: "Carte graphique Sapphire RX 6600 8GB"
-> {{"reason": "Carte graphique PC correspondant à la recherche 6600.", "short_advice": "Bonne affaire à vérifier.", "is_good_deal": true}}

SEARCH: "6600" | TITLE: "Set van 5 vintage Emile Henry France terrine 6600"
-> {{"reason": "Terrines de cuisine, objet non informatique.", "short_advice": "À éviter.", "is_good_deal": false}}

SEARCH: "6600" | TITLE: "Téléphone Nokia 6600 Vintage"
-> {{"reason": "Téléphone portable, objet non informatique.", "short_advice": "À éviter.", "is_good_deal": false}}

Write 'reason' and 'short_advice' in concise French (1 sentence max each).
"""

    system_prompt = (
        "You are a strict JSON backend API for PC deal validation. "
        "You run 100% statelessly without conversation memory. "
        "Output ONLY a valid JSON object with keys in exact order: reason (string in French), short_advice (string in French), is_good_deal (boolean). "
        "Do not include markdown tags or intro text."
    )

    try:
        response = await client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            extra_body={
                "cache_prompt": False,
                "grammar": DEAL_RESPONSE_GBNF
            },
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "DealResponse",
                    "strict": True,
                    "schema": DealResponse.model_json_schema(),
                },
            },
            max_tokens=256,
        )

        raw_content = response.choices[0].message.content
        if not raw_content:
            logger.warning("Réponse vide reçue de llama-server.")
            return None, None

        parsed = repair_and_parse_deal_json(raw_content)

        # Sécurité Python : incohérence entre texte et is_good_deal
        reason_lower = (parsed.reason + " " + parsed.short_advice).lower()
        if parsed.is_good_deal and any(
            trig in reason_lower
            for trig in [
                "à éviter",
                "a eviter",
                "hors-sujet",
                "hors sujet",
                "rejet",
                "défectueux",
                "pas un composant",
                "non informatique",
                "non spécifiée",
                "non precisee",
            ]
        ):
            logger.warning(
                "Incohérence IA détectée pour '%s' (is_good_deal=True mais texte de rejet). Correction en is_good_deal=False.",
                title,
            )
            parsed.is_good_deal = False

        logger.debug(
            "[Llama Analysis OK] Valide: %s | Raison: %s",
            parsed.is_good_deal,
            parsed.reason,
        )

        status_icon = "Bonne affaire" if parsed.is_good_deal else "À éviter"
        formatted_analysis = (
            f"**Statut :** {status_icon}\n"
            f"**Analyse :** {parsed.reason}\n"
            f"**Conseil :** {parsed.short_advice}"
        )
        return formatted_analysis, parsed.is_good_deal

    except Exception as e:
        logger.warning(
            "⚠️ Impossible d'analyser l'annonce avec llama-server sur %s : [%s]",
            LLAMA_HOST,
            type(e).__name__,
        )
        return None, None


# Alias pour rétrocompatibilité
analyzeDealWithOllama = analyzeDealWithLlama
