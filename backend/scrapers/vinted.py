import asyncio
import json
import re
import urllib.parse
from random import randint

import httpx
from bs4 import BeautifulSoup
from filters import checkTitleRelevance
from logger import logger
from scrapers.item import ScrapedItem


class VintedScraper:
    """
    Scraper pour Vinted utilisant des requêtes HTTP asynchrones légères (httpx)
    sur le catalogue Vinted et la récupération du contexte LD+JSON des annonces.
    """

    async def scrape(self, query: str, maxPrice: float = 0.0, maxPages: int = 1, maxItems: int = 30) -> list:
        """Exécute un cycle de scraping asynchrone sur Vinted pour une recherche donnée."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        logger.debug("[Vinted-Scraper] Recherche en cours: '%s' (max %s pages)", query, maxPages)
        formattedItems = []
        encodedQuery = urllib.parse.quote_plus(query)

        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=15.0) as client:
                # Étape 1 : Obtenir les cookies de session Vinted
                await client.get("https://www.vinted.fr")

                seen_ids = set()

                for page_num in range(1, maxPages + 1):
                    logger.debug("   - Chargement de la page Vinted %s...", page_num)
                    url = f"https://www.vinted.fr/catalog?search_text={encodedQuery}&order=newest_first&page={page_num}&status_ids[]=6&status_ids[]=1&status_ids[]=2"
                    if maxPrice and float(maxPrice) > 0:
                        url += f"&price_to={float(maxPrice)}"

                    resp = await client.get(url)

                    if resp.status_code != 200:
                        logger.error("[Vinted-Scraper] Échec HTTP %s sur la page %s.", resp.status_code, page_num)
                        if resp.status_code == 403:
                            raise Exception("403 Forbidden (Banni par Vinted)")
                        raise Exception(f"Erreur HTTP {resp.status_code}")

                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.find_all("a", href=re.compile(r"/items/\d+"))

                    if not links:
                        logger.debug("   - Fin des résultats Vinted sur la page %s.", page_num)
                        break

                    page_items = []

                    for link in links:
                        if maxItems and len(seen_ids) >= maxItems:
                            break

                        href = link.get("href")
                        if not href:
                            continue

                        match = re.search(r"/items/(\d+)", href)
                        if not match:
                            continue

                        externalId = match.group(1)
                        if externalId in seen_ids:
                            continue
                        seen_ids.add(externalId)

                        item_url = href if href.startswith("http") else "https://www.vinted.fr" + href
                        title_attr = link.get("title") or ""
                        text = link.text.strip()

                        # Extraction du prix
                        price = 0.0
                        price_match = re.search(r"(\d+(?:[\.,\s]\d+)?)\s*€", title_attr or text)
                        if price_match:
                            try:
                                price = float(price_match.group(1).replace(" ", "").replace(",", "."))
                            except ValueError:
                                pass

                        # Extraction du titre
                        title = ""
                        if title_attr:
                            clean = re.split(r",\s*(?:Marque|État|Taille|Modèle):", title_attr)[0].strip()
                            clean = re.sub(r",?\s*\d+[\.,]?\d*\s*€.*$", "", clean).strip()
                            title = clean
                        if not title:
                            title = text.split("\n")[0] if text else "Sans titre"

                        # Extraction de l'image
                        card = link.parent or link
                        img = card.find("img") or link.find("img")
                        imageUrl = (img.get("src") or img.get("data-src")) if img else None

                        scraped_item = ScrapedItem(
                            externalId=externalId,
                            title=title,
                            price=price,
                            url=item_url,
                            site="vinted",
                            imageUrl=imageUrl,
                            publishedAt=None
                        )

                        if maxPrice and price > maxPrice:
                            continue

                        queryWords = [w for w in query.lower().split() if len(w) > 2 and w != "pc"]
                        title_has_all = queryWords and all(w in title.lower() for w in queryWords)

                        if title_has_all or checkTitleRelevance(title.lower(), query.lower()):
                            page_items.append(scraped_item)

                    for scraped_item in page_items:
                        logger.debug("   - Chargement de la description Vinted : '%s' (%s €)", scraped_item.title, scraped_item.price)
                        await scraped_item.fetchDescription(client)
                        await asyncio.sleep(randint(100, 300) / 1000.0)
                        formattedItems.append(scraped_item)

                    await asyncio.sleep(randint(300, 800) / 1000.0)

                logger.debug("[Vinted-Scraper] %s annonces extraites avec succès au total.", len(formattedItems))
                return formattedItems

        except Exception as e:
            logger.error("[Vinted-Scraper] Erreur de scraping : [%s] %s", type(e).__name__, e or repr(e))
            raise
