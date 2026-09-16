import asyncio
import re
import urllib.parse
from random import randint

from camoufox.async_api import AsyncCamoufox
from filters import checkTitleRelevance
from logger import logger

from scrapers.item import ScrapedItem


class VintedScraper:
    """
    Scraper pour Vinted utilisant Camoufox (Firefox anti-détection Async headless)
    pour charger les annonces depuis la page de catalogue Vinted et contourner le blocage API 404.
    """

    async def scrape(self, query: str, maxPrice: float = 0.0, maxPages: int = 1, maxItems: int = 30, browser=None) -> list:
        logger.info("[Vinted-Scraper] Recherche en cours: '%s' (max %s pages, max %s annonces)", query, maxPages, maxItems)
        try:
            if browser is None:
                async with AsyncCamoufox(headless=True) as local_browser:
                    return await self._scrape_with_browser(query, maxPrice, maxPages, maxItems, local_browser)
            else:
                return await self._scrape_with_browser(query, maxPrice, maxPages, maxItems, browser)
        except Exception as e:
            logger.error("[Vinted-Scraper] Erreur de scraping : [%s] %s", type(e).__name__, e or repr(e))
            raise

    async def _scrape_with_browser(self, query: str, maxPrice: float, maxPages: int, maxItems: int, browser) -> list:
        formattedItems = []
        encodedQuery = urllib.parse.quote_plus(query)

        contexts = browser.contexts
        context = contexts[0] if contexts else await browser.new_context()
        page = await context.new_page()

        try:
            for page_num in range(1, maxPages + 1):
                logger.info("   - Chargement de la page Vinted %s...", page_num)
                url = f"https://www.vinted.fr/catalog?search_text={encodedQuery}&order=newest_first&page={page_num}"
                if maxPrice and float(maxPrice) > 0:
                    url += f"&price_to={float(maxPrice)}"

                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                if not response or response.status != 200:
                    status_code = response.status if response else 0
                    logger.error("[Vinted-Scraper] Échec HTTP %s sur la page %s.", status_code, page_num)
                    if status_code == 403:
                        raise Exception("403 Forbidden (Banni par Vinted)")
                    raise Exception(f"Erreur HTTP {status_code}")

                await page.wait_for_timeout(randint(1500, 2500))

                links = await page.query_selector_all("a[href*=\"/items/\"]")
                if not links:
                    logger.info("   - Fin des résultats Vinted sur la page %s.", page_num)
                    break

                seen_ids = set()
                page_items = []

                for link in links:
                    if maxItems and len(seen_ids) >= maxItems:
                        break
                    href = await link.get_attribute("href")
                    if not href or "/items/" not in href:
                        continue

                    if not href.startswith("http"):
                        item_url = "https://www.vinted.fr" + href
                    else:
                        item_url = href

                    item_id_match = re.search(r"/items/(\d+)", item_url)
                    if not item_id_match:
                        continue
                    externalId = item_id_match.group(1)

                    if externalId in seen_ids:
                        continue
                    seen_ids.add(externalId)

                    card = await link.evaluate_handle("""el => {
                        let p = el;
                        for (let k = 0; k < 5; k++) {
                            if (p.parentElement) p = p.parentElement;
                            if (p.innerText && p.innerText.includes("€")) return p;
                        }
                        return el;
                    }""")

                    card_text = await card.evaluate("el => el ? el.innerText : \"\"") or ""
                    imageUrl = await card.evaluate("""el => {
                        if (!el) return null;
                        const img = el.querySelector("img");
                        return img ? (img.src || img.getAttribute("data-src")) : null;
                    }""")
                    title_attr = await link.get_attribute("title") or ""

                    # Extraction robuste du prix
                    price = 0.0
                    price_match = re.search(r"(\d+(?:[\.,\s]\d+)?)\s*€", card_text)
                    if not price_match and title_attr:
                        price_match = re.search(r"(\d+(?:[\.,]\d+)?)\s*€", title_attr)
                    if price_match:
                        try:
                            price = float(price_match.group(1).replace(" ", "").replace(",", "."))
                        except ValueError:
                            pass

                    # Extraction propre du titre
                    title = ""
                    if title_attr:
                        clean = re.split(r",\s*(?:Marque|État|Taille):", title_attr)[0].strip()
                        clean = re.sub(r",?\s*\d+[\.,]?\d*\s*€.*$", "", clean).strip()
                        title = clean
                    if not title:
                        lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                        title = lines[0] if lines else "Sans titre"

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
                    logger.info("   - Chargement de la description Vinted : '%s' (%s €)", scraped_item.title, scraped_item.price)
                    item_page = await context.new_page()
                    try:
                        await scraped_item.fetchDescription(item_page)
                    finally:
                        await item_page.close()
                    await asyncio.sleep(randint(100, 300) / 1000.0)
                    formattedItems.append(scraped_item)

                await asyncio.sleep(randint(300, 800) / 1000.0)

            logger.info("[Vinted-Scraper] %s annonces extraites avec succès au total.", len(formattedItems))
            return formattedItems

        finally:
            await page.close()
