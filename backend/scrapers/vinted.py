import asyncio
from random import randint

import httpx
from filters import checkTitleRelevance
from logger import logger

from scrapers.item import ScrapedItem


class VintedScraper:
    """
    Scraper pour Vinted utilisant des requêtes HTTP asynchrones (httpx) avec persistance de session
    pour récupérer directement le JSON depuis leur API interne.
    """
    
    async def scrape(self, query: str, maxPrice: float = 0.0, maxPages: int = 1) -> list:

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        
        logger.info("[Vinted-Scraper] Recherche en cours: '%s' (max 3 pages, cat: 3564)", query)
        formattedItems = []
        
        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
                # Étape 1 : Obtenir les cookies de session
                await client.get("https://www.vinted.fr")
                
                apiUrl = "https://www.vinted.fr/api/v2/catalog/items"
                
                # catalog_ids=3582 : pièces détachées informatiques
                # catalog_ids=3564 : informatiques (général) 
                params = {
                    "search_text": query,
                    "order": "newest_first",
                    "per_page": 96,
                    "catalog_ids": 3564
                }
                
                if maxPrice != 0.0:
                    params["price_to"] = maxPrice
                    
                for page_num in range(1, maxPages + 1):
                    logger.info("   - Chargement de la page Vinted %s...", page_num)
                    params["page"] = page_num
                    
                    apiResp = await client.get(apiUrl, params=params)
                    
                    if apiResp.status_code != 200:
                        logger.error("[Vinted-Scraper] Échec API HTTP %s sur la page %s.", apiResp.status_code, page_num)
                        if apiResp.status_code == 403:
                            raise Exception("403 Forbidden (Banni par Vinted)")
                        raise Exception(f"Erreur HTTP {apiResp.status_code}")
                        
                    data = apiResp.json()
                    items = data.get("items", [])
                    
                    if not items:
                        logger.info("   - Fin des résultats Vinted sur la page %s.", page_num)
                        break
                        
                    for item in items:
                        externalId = str(item.get("id", ""))
                        if not externalId:
                            continue
                            
                        price = float(item.get("price", {}).get("amount", 0))
                        title = item.get("title", "Sans titre")
                        
                        # Création de l'objet ScrapedItem
                        photo = item.get("photo", {}) or {}
                        imageUrl = photo.get("url", None)
                        
                        scraped_item = ScrapedItem(
                            externalId=externalId,
                            title=title,
                            price=price,
                            url=item.get("url", ""),
                            site="vinted",
                            imageUrl=imageUrl,
                            publishedAt=None
                        )
                        
                        # Étape 4 : Filtrage de pertinence avant de lancer un fetch de description
                        if maxPrice is not None and price > maxPrice:
                            continue
                            
                        queryWords = [w for w in query.lower().split() if len(w) > 2 and w != "pc"]
                        title_has_all = queryWords and all(w in title.lower() for w in queryWords)
                        
                        # Si le titre contient déjà tous les mots-clés significatifs de la recherche, c'est validé d'office sans fetch,
                        # SAUF si le prix est anormalement bas (ex: < 40% du prix max, ce qui cache souvent une boîte vide ou un accessoire)
                        is_suspicious_price = maxPrice is not None and price < (0.4 * maxPrice)
                        
                        if title_has_all and not is_suspicious_price:
                            formattedItems.append(scraped_item)
                        elif title_has_all or checkTitleRelevance(title.lower(), query.lower()):
                            # Si le titre a tous les mots mais à prix suspect, OU si le titre est générique, on force le fetch
                            logger.info("   - Récupération de la description complète pour : '%s' (prix suspect: %s€)", title, price)
                            await scraped_item.fetchDescription(client)
                            
                            # On valide uniquement si la description contient bien tous les mots recherchés
                            desc_lower = (scraped_item.description or "").lower()
                            if queryWords and all(w in desc_lower for w in queryWords):
                                formattedItems.append(scraped_item)
                                await asyncio.sleep(randint(100, 400) / 1000.0)  # Pause uniquement si on a fait un fetch
                            else:
                                logger.warning("   - Annonce rejetée (mots-clés absents de la description) : '%s'", title)
                        
                    # Pause entre les pages
                    await asyncio.sleep(randint(200, 600) / 1000.0)  # Pause courte en millisecondes (200ms - 600ms)
                    
                logger.info("[Vinted-Scraper] %s annonces extraites avec succès au total.", len(formattedItems))
                return formattedItems
                
        except Exception as e:
            logger.error("[Vinted-Scraper] Erreur de scraping : %s", e)
            raise
