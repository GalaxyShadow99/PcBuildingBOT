def checkTitleRelevance(titleLower: str, queryLower: str) -> bool:
    """
    Vérifie si le titre de l'annonce est pertinent par rapport à la recherche en cours.
    Retourne True si un mot-clé direct est trouvé, ou si le titre appartient lexicalement à la même
    famille de composants tout en n'appartenant pas à une autre famille (exclusion croisée).
    """
    # 1. Si TOUS les mots clés de la recherche (hors "pc") sont directement dans le titre (Cas idéal)
    queryWords = [w for w in queryLower.split() if len(w) > 2 and w != "pc"]
    if queryWords and all(word in titleLower for word in queryWords):
        return True

    # 1b. Si la recherche contient un numéro de modèle à 3, 4 ou 5 chiffres (ex: 2060, 3600, 12100),
    # et que le titre contient un AUTRE numéro de modèle, on exclut immédiatement.
    import re
    queryNumbers = re.findall(r'\d{3,5}', queryLower)
    if queryNumbers:
        titleNumbers = re.findall(r'\d{3,5}', titleLower)
        for num in titleNumbers:
            if num not in queryNumbers:
                return False

    # 1c. Détection et comparaison intelligente des capacités de RAM / Stockage (ex: 16Go vs 32Go)
    queryCap = re.findall(r'(\d+)\s*(?:go|gb|gig|to|tb)', queryLower)
    if queryCap:
        titleCaps = re.findall(r'(\d+)\s*(?:go|gb|gig|to|tb)', titleLower)
        for cap in titleCaps:
            if cap not in queryCap:
                # Tolérance pour les kits (ex: 2x16Go pour une recherche de 32Go)
                if cap == "16" and "32" in queryCap and ("2x" in titleLower or "2 " in titleLower or "lot" in titleLower):
                    continue
                if cap == "8" and "16" in queryCap and ("2x" in titleLower or "2 " in titleLower or "lot" in titleLower):
                    continue
                return False
            
    # 2. Définition des familles de composants pour l'exclusion croisée
    categories = {
        "gpu": ["rtx", "gtx", "gpu", "carte graphique", "cg", "radeon"],
        "cpu": ["ryzen", "intel", "cpu", "processeur", "i3", "i5", "i7", "i9"],
        "motherboard": ["carte mere", "carte mère", "motherboard", "mobo", "b450", "b550", "x570", "am4"],
        "ram": ["ram", "ddr", "memoire", "mémoire"],
        "storage": ["ssd", "hdd", "disque dur", "disque"],
        "alim": ["alim", "alimentation", "power supply", "psu", "netzteil"],
        "case": ["boitier", "boîtier", "case", "tour"]
    }
    
    # Identifier la famille de la recherche de l'utilisateur
    queryCategory = None
    for catName, catKeywords in categories.items():
        if any(k in queryLower for k in catKeywords):
            queryCategory = catName
            break
            
    # Si la recherche ne correspond à aucun composant connu, on applique la règle stricte
    if not queryCategory:
        return False
        
    # Si le titre contient un mot-clé d'une AUTRE famille de composants, on l'exclut d'office
    for catName, catKeywords in categories.items():
        if catName != queryCategory:
            if any(k in titleLower for k in catKeywords):
                return False
                
    # Si aucun mot d'une autre catégorie n'est présent, on autorise le titre générique
    # à condition qu'il contienne au moins un synonyme de la famille recherchée
    categorySynonyms = {
        "gpu": ["carte", "graphique", "gpu", "cg"],
        "cpu": ["cpu", "processeur"],
        "motherboard": ["carte", "mere", "mère", "motherboard", "mobo"],
        "ram": ["ram", "ddr", "memoire", "mémoire", "go"],
        "storage": ["ssd", "hdd", "disque", "dur", "to", "go"],
        "alim": ["alim", "alimentation", "power", "supply", "watt", "watts", "psu", "netzteil"],
        "case": ["boitier", "boîtier", "case", "tour"]
    }
    
    synonyms = categorySynonyms.get(queryCategory, [])
    if any(s in titleLower for s in synonyms):
        return True
        
    return False


def checkHardwareModelCompatibility(titleLower: str, queryLower: str, descriptionLower: str = "") -> bool:
    """
    Vérification déterministe stricte des modèles matériels, chipsets et générations de RAM en Python.
    Évite 100% des hallucinations des petits LLM (ex: B85 pris pour H610, DDR3 prise pour DDR4).
    """
    full_text = (titleLower + " " + (descriptionLower or "")).lower()

    # 1. Vérification des chipsets de cartes mères
    mobo_chipsets = [
        "h610", "b660", "b760", "z690", "z790", "h510", "b560", "z590", "h410", "b460", "z490", 
        "h310", "b360", "b365", "z370", "z390", "h110", "b150", "b250", "z170", "z270",
        "h81", "b85", "h87", "z87", "z97", "h77", "z77", "h61", "p67", "z68",
        "a320", "b350", "b450", "b550", "x370", "x470", "x570", "a520", "a620", "b650", "x670"
    ]
    req_chipsets = [c for c in mobo_chipsets if c in queryLower]
    if req_chipsets:
        if not any(c in full_text for c in req_chipsets):
            return False

    # 2. Généralisation RAM DDR3 / DDR4 / DDR5
    if "ddr4" in queryLower and "ddr4" not in full_text:
        if "ddr3" in full_text or "ddr5" in full_text:
            return False
    if "ddr5" in queryLower and "ddr5" not in full_text:
        if "ddr4" in full_text or "ddr3" in full_text:
            return False
    if "ddr3" in queryLower and "ddr3" not in full_text:
        if "ddr4" in full_text or "ddr5" in full_text:
            return False

    # 3. Format SODIMM / Portable vs PC Fixe pour la RAM
    has_ram_kw = any(k in queryLower for k in ["ram", "ddr", "memoire", "mémoire"])
    has_sodimm_kw = any(k in queryLower for k in ["sodimm", "so-dimm", "portable", "laptop", "notebook"])
    if has_ram_kw and not has_sodimm_kw:
        if any(k in full_text for k in ["sodimm", "so-dimm", "pc portable", "laptop", "notebook"]):
            return False

    return True
