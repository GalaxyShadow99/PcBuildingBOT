import json
import urllib.parse
from random import randint

from camoufox.async_api import AsyncCamoufox
from logger import logger

from scrapers.item import ScrapedItem


class LeBonCoinScraper:
    """
    Scraper pour LeBonCoin utilisant Camoufox (Firefox anti-détection Async headless)
    et extrayant les données depuis le bloc __NEXT_DATA__ par découpage de texte.
    """
    
    async def scrape(self, query: str, category: int = 15, maxPages: int = 2, browser=None) -> list:
        logger.info("[LBC-Scraper] Recherche en cours : '%s' (%s pages max)", query, maxPages)
        try:
            if browser is None:
                async with AsyncCamoufox(headless=True) as local_browser:
                    return await self._scrape_with_browser(query, category, maxPages, local_browser)
            else:
                return await self._scrape_with_browser(query, category, maxPages, browser)
        except Exception as e:
            logger.error("[LBC-Scraper] Erreur de scraping : %s", e)
            raise

    async def _scrape_with_browser(self, query: str, category: int, maxPages: int, browser) -> list:
        formattedAds = []
        encodedQuery = urllib.parse.quote_plus(query)
        
        # Ouvre un nouvel onglet temporaire pour cette recherche
        page = await browser.new_page()
        
        try:
            for i in range(maxPages):
                pageNum = i + 1
                url = f"https://www.leboncoin.fr/recherche?category={category}&text={encodedQuery}&sort=time&page={pageNum}"
                logger.info("   - Chargement de la page %s...", pageNum)
                
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                if response.status != 200:
                    logger.error("[LBC-Scraper] Code HTTP %s %s sur la page %s. Arrêt du scan.", response.status, response.status_text, pageNum)
                    if response.status == 403:
                        raise Exception("403 Forbidden (Banni par LeBonCoin)")
                    raise Exception(f"Erreur HTTP {response.status}")
                    
                await page.wait_for_timeout(randint(1023, 2341))
                htmlContent = await page.content()
                
                startMarker = 'id="__NEXT_DATA__"'
                if startMarker not in htmlContent:
                    logger.error("[LBC-Scraper] Balise __NEXT_DATA__ introuvable sur la page %s.", pageNum)
                    break
                    
                startPos = htmlContent.find(startMarker)
                jsonStart = htmlContent.find('>', startPos) + 1
                jsonEnd = htmlContent.find('</script>', jsonStart)
                
                rawJsonStr = htmlContent[jsonStart:jsonEnd]
                rawJson = json.loads(rawJsonStr)
                
                pageProps = rawJson.get("props", {}).get("pageProps", {})
                searchData = pageProps.get("searchData", {})
                ads = searchData.get("ads", [])
                
                if not ads:
                    logger.info("   - Fin des résultats sur la page %s.", pageNum)
                    break
                    
                for ad in ads:
                    priceList = ad.get("price", [])
                    price = priceList[0] if isinstance(priceList, list) and priceList else (priceList if isinstance(priceList, (int, float)) else 0)
                    
                    images = ad.get("images", {})
                    imageUrls = images.get("urls", [])
                    imageUrl = imageUrls[0] if imageUrls else images.get("thumb_url", None)
                    
                    externalId = str(ad.get("list_id") or ad.get("id") or "")
                    if not externalId:
                        continue
                        
                    formattedAds.append(ScrapedItem(
                        externalId=externalId,
                        title=ad.get("subject", "Sans titre"),
                        price=price,
                        url=ad.get("url", ""),
                        site="leboncoin",
                        imageUrl=imageUrl,
                        publishedAt=ad.get("first_publication_date", "")
                    ))
                    
            logger.info("[LBC-Scraper] %s annonces extraites au total.", len(formattedAds))
            
        finally:
            # Ferme l'onglet de navigation pour libérer la RAM, tout en laissant le navigateur ouvert
            await page.close()
            
        return formattedAds
