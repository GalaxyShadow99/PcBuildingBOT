class ScrapedItem:
    """
    Classe représentant une annonce indépendamment du site
    """
    def __init__(self, externalId, title, price, url, site, imageUrl=None, publishedAt=None, description=None):
        self.externalId = str(externalId)
        self.title = title
        self.price = float(price)
        self.url = url
        self.site = site
        self.imageUrl = imageUrl
        self.publishedAt = publishedAt
        self.description = description

    def isBroken(self) -> bool:
        """Détecte si le composant est en panne ou vendu pour pièces (inclut les modifs utilisateur)."""
        titleLower = self.title.lower()
        brokenWords = [
            "hs", "semi hs", "panne", "cassé", "cassée", "non fonctionnel", 
            "non fonctionnelle", "pour pièces", "pour pieces", "endommagé", 
            "endommagée", "défectueux", "défectueuse", "untested", "non testé", 
            "non teste", "réparateur", "réparatrice", "non réparable", "non reparable", 
            "à réparer", "a reparer", "à réparer", "a réparer", "a reparer",
            "boite vide", "boîte vide", "box only", "boite seule", "boîte seule", 
            "empty box", "boite de", "boîte de", "boite pour", "boîte pour", 
            "carton de", "carton pour", "boite d'emballage", "boîte d'emballage",
            "radiateur", "radiador", "da testare", "per ricambi", "ricambi", "ricambio",
            "para desguace", "para despiece", "repuesto", "repuestos",
            "ventilador", "waterblock", "water block", "cd-rom", "cdrom", "driver", "drivers", "koeler", "koelers",
            "dvd", "manual", "manuel", "caixa", "No GPU", "no gpu", "sin gpu", "sin tarjeta grafica", "sin tarjeta gráfica",
            "GPU not included", "gpu not included", "sin gpu incluida", "sin gpu incluida", "sin tarjeta grafica incluida", "sin tarjeta gráfica incluida",
        ]
        if any(word in titleLower for word in brokenWords):
            return True
            
        if self.description:
            descLower = self.description.lower()
            if any(word in descLower for word in brokenWords):
                return True
                
        return False

    async def fetchDescription(self, client_or_page) -> bool:
        """Charge la page de l'annonce Vinted et extrait la description depuis le bloc LD+JSON ou le DOM."""
        import re
        import json
        try:
            if hasattr(client_or_page, "goto"):
                page = client_or_page
                try:
                    response = await page.goto(self.url, wait_until="domcontentloaded", timeout=10000)
                except Exception as goto_err:
                    from logger import logger
                    logger.warning("⏱️ Timeout ou interruption lors du chargement de %s : %s", self.url, goto_err)
                    return False

                if response and response.status == 200:
                    html = await page.content()
                    ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
                    for block in ld_blocks:
                        try:
                            data = json.loads(block.strip())
                            if isinstance(data, dict) and data.get("@type") == "Product":
                                self.description = data.get("description", "")
                                if self.description:
                                    return True
                        except Exception:
                            continue
                    
                    desc_el = await page.query_selector('[itemprop="description"], [data-testid="item-description"], .item-description, [class*="item-description"]')
                    if desc_el:
                        self.description = (await desc_el.inner_text()).strip()
                        return True
            else:
                client = client_or_page
                response = await client.get(self.url, timeout=10)
                if response.status_code == 200:
                    ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', response.text, re.DOTALL)
                    for block in ld_blocks:
                        try:
                            data = json.loads(block.strip())
                            if isinstance(data, dict) and data.get("@type") == "Product":
                                self.description = data.get("description", "")
                                return True
                        except Exception:
                            continue
        except Exception as e:
            from logger import logger
            logger.warning("❌ Erreur lors de la récupération de la description Vinted : %s", e)
        return False

    def getDealPercentage(self, maxPrice: float) -> int:
        """Calcule le pourcentage d'économie réalisé par rapport au budget max."""
        if maxPrice <= 0:
            return 0
        discount = ((maxPrice - self.price) / maxPrice) * 100
        return max(0, int(discount))

    def requiresPickup(self) -> bool:
        """Détecte si la remise en main propre uniquement est exigée (pas d'envoi)."""
        titleLower = self.title.lower()
        pickupWords = ["pas d'envoi", "pas denvoi", "main propre", "uniquement sur place"]
        return any(word in titleLower for word in pickupWords)

    def toDiscordEmbed(self, maxPrice: float, keywords: str, aiAnalysis: str = None) -> dict:
        """Génère le dictionnaire de payload (embed) pour Discord."""
        siteName = self.site.capitalize()
        discount = self.getDealPercentage(maxPrice)
        
        title = f"{self.title} | {self.price} €"
        if discount >= 15:
            title = f"🔥 [{discount}% Off] {self.title}"
            
        color = 16737792 if discount >= 15 else 3447003
        shippingStatus = "Main propre uniquement (Pas d'envoi)" if self.requiresPickup() else "Envoi possible"
        
        fields = [
            {
                "name": "Prix",
                "value": f"**{self.price} €** (Max : {maxPrice} €)",
                "inline": True
            },
            {
                "name": "Recherche",
                "value": f"`{keywords}`",
                "inline": True
            },
            {
                "name": "Livraison",
                "value": shippingStatus,
                "inline": True
            },
            {
                "name": "Provenance",
                "value": siteName,
                "inline": True
            }
        ]

        if aiAnalysis:
            fields.append({
                "name": "Analyse Qwen",
                "value": aiAnalysis,
                "inline": False
            })
        
        embed = {
            "title": title,
            "url": self.url,
            "color": color,
            "fields": fields,
            "footer": {
                "text": "LBCBot"
            }
        }
        
        if self.imageUrl:
            embed["thumbnail"] = {"url": self.imageUrl}
            
        return {"embeds": [embed]}
