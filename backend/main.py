import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from random import randint
from typing import Any

import uvicorn
from database import *
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from filters import checkTitleRelevance
from logger import logger
from notifier import deleteDiscordMessage, sendDiscordNotification
from pydantic import BaseModel
from scrapers import LeBonCoinScraper, VintedScraper
from starlette.exceptions import HTTPException as StarletteHTTPException


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialisation de la base SQLite
    initDb()
    # Lancement de la tâche de fond de surveillance périodique
    task = asyncio.create_task(runPeriodicScans())
    yield
    task.cancel()

app = FastAPI(title="LBCBot API", lifespan=lifespan)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")
if not API_SECRET_KEY:
    logger.fatal("Aucune clé API définie. Les appels POST/DELETE seront refusés.")
    sys.exit(1)
if not DISCORD_WEBHOOK_URL:
    logger.fatal("Aucun webhook Discord défini. Les notifications ne seront pas envoyées.")
    sys.exit(1)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verifyApiKey(key: str = Depends(api_key_header)):
    if not API_SECRET_KEY:
        return
    if key != API_SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail="Clé API invalide ou manquante."
        )

# Format de réponse unifié pour tout l'API
def apiResponse(success: bool, data: Any = None, error: str = None):
    return {
        "success": success,
        "data": data,
        "error": error
    }

SCRAPER_HEALTH = {
    "leboncoin": {
        "status": "Inconnu",
        "last_scrape": None,
        "error": None,
        "cooldown_until": None
    },
    "vinted": {
        "status": "Inconnu",
        "last_scrape": None,
        "error": None,
        "cooldown_until": None
    }
}

def updateHealth(site: str, status: str, error_msg: str = None, cooldown_mins: int = 0):
    cooldown_until = None
    if cooldown_mins > 0:
        cooldown_until = (datetime.utcnow() + timedelta(minutes=cooldown_mins)).isoformat()
    
    if status == "OK":
        cooldown_until = None
    elif cooldown_until is None and SCRAPER_HEALTH[site].get("cooldown_until"):
        cooldown_until = SCRAPER_HEALTH[site]["cooldown_until"]

    SCRAPER_HEALTH[site] = {
        "status": status,
        "last_scrape": datetime.utcnow().isoformat(),
        "error": error_msg,
        "cooldown_until": cooldown_until
    }

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=apiResponse(False, error=exc.detail)
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content=apiResponse(False, error="Données de validation invalides.")
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.exception("Erreur système non gérée : %s", exc)
    return JSONResponse(
        status_code=500,
        content=apiResponse(False, error="Une erreur interne du serveur est survenue.")
    )


class WatchlistCreate(BaseModel):
    keywords: str
    maxPrice: float
    category: int = 15

class WatchlistUpdate(BaseModel):
    keywords: str
    maxPrice: float
    category: int = 15
    enabled: bool = True

# Instanciation des scrapers
lbcScraper = LeBonCoinScraper()
vintedScraper = VintedScraper()

async def fetchLbcDescription(url: str, browser) -> str:
    """Ouvre temporairement l'URL de l'annonce LBC pour en extraire la description."""
    if not url:
        return ""
    page = await browser.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        if response.status == 200:
            html = await page.content()
            startMarker = 'id="__NEXT_DATA__"'
            if startMarker in html:
                startPos = html.find(startMarker)
                jsonStart = html.find('>', startPos) + 1
                jsonEnd = html.find('</script>', jsonStart)
                rawJsonStr = html[jsonStart:jsonEnd]
                rawJson = json.loads(rawJsonStr)
                ad_details = rawJson.get("props", {}).get("pageProps", {}).get("ad", {})
                return ad_details.get("description", "")
    except Exception as e:
        logger.error("Erreur lors de la récupération de la description LBC : %s", e)
    finally:
        await page.close()
    return ""

DISCORD_MAX_MESSAGES = 25

def cleanupOldDiscordMessages():
    """
    Maintient le canal Discord propre en ne gardant que les 25 derniers messages envoyés.
    Supprime les plus anciens du canal Discord et nettoie la base SQLite.
    """
    if not DISCORD_WEBHOOK_URL:
        return
        
    conn = getDbConnection()
    cursor = conn.cursor()
    try:
        # Sélectionner tous les produits qui ont un message ID Discord
        cursor.execute("""
            SELECT id, discordMessageId 
            FROM products 
            WHERE discordMessageId IS NOT NULL 
            ORDER BY notifiedAt DESC
        """)
        rows = cursor.fetchall()
        
        if len(rows) > DISCORD_MAX_MESSAGES:
            # Les messages à supprimer sont ceux après les DISCORD_MAX_MESSAGES plus récents
            to_delete = rows[DISCORD_MAX_MESSAGES:]
            logger.info("🧹 Nettoyage de %s anciens messages Discord...", len(to_delete))
            for db_id, msg_id in to_delete:
                # Supprimer de Discord
                deleteDiscordMessage(DISCORD_WEBHOOK_URL, msg_id)
                # Mettre à jour en base pour ne plus essayer de le supprimer
                cursor.execute("UPDATE products SET discordMessageId = NULL WHERE id = ?", (db_id,))
                conn.commit()
    except Exception as e:
        logger.error("❌ Erreur lors du nettoyage des anciens messages Discord : %s", e)
    finally:
        conn.close()

async def runScan(force: bool = False):
    """Effectue un cycle de scan sur toute la watchlist active"""
    logger.info("Début du cycle de scan global...")
    
    # Récupération des recherches actives en unpacking de tuples
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, keywords, maxPrice, category FROM watchlist WHERE enabled = 1")
    activeItems = cursor.fetchall()
    conn.close()
    
    if not activeItems:
        logger.info("Aucune recherche active dans la watchlist.")
        return
 
    from camoufox.async_api import AsyncCamoufox
    
    # On ouvre le navigateur Camoufox UNE SEULE fois pour tout le cycle de scan LBC
    async with AsyncCamoufox(headless=True) as browser:
        for itemId, keywords, maxPrice, category in activeItems:
            logger.info("Scan de '%s' (max %s€)...", keywords, maxPrice)
            
            # Scraping asynchrone sécurisé pour le health check (LeBonCoin)
            is_lbc_cooldown = False
            lbc_cooldown_str = SCRAPER_HEALTH["leboncoin"].get("cooldown_until")
            if lbc_cooldown_str and not force:
                cooldown_dt = datetime.fromisoformat(lbc_cooldown_str)
                if datetime.utcnow() < cooldown_dt:
                    is_lbc_cooldown = True
                    logger.info("[Scan LBC] Ignoré (cooldown actif suite à un ban 403)")
            
            if not is_lbc_cooldown:
                try:
                    lbcAds = await lbcScraper.scrape(keywords, category, browser=browser)
                    updateHealth("leboncoin", "OK")
                except Exception as e:
                    logger.error("[Scan LBC] Échec : %s", e)
                    status_msg = "Bloqué (403)" if "403" in str(e) else "Erreur"
                    cooldown_mins = 30 if "403" in str(e) else 0
                    updateHealth("leboncoin", status_msg, str(e), cooldown_mins=cooldown_mins)
                    lbcAds = []
            else:
                lbcAds = []
 
            # Scraping asynchrone sécurisé pour le health check (Vinted)
            is_vinted_cooldown = False
            vinted_cooldown_str = SCRAPER_HEALTH["vinted"].get("cooldown_until")
            if vinted_cooldown_str and not force:
                cooldown_dt = datetime.fromisoformat(vinted_cooldown_str)
                if datetime.utcnow() < cooldown_dt:
                    is_vinted_cooldown = True
                    logger.info("[Scan Vinted] Ignoré (cooldown actif suite à un ban 403)")
            
            if not is_vinted_cooldown:
                try:
                    vintedAds = await vintedScraper.scrape(keywords, maxPrice=maxPrice)
                    updateHealth("vinted", "OK")
                except Exception as e:
                    logger.error("[Scan Vinted] Échec : %s", e)
                    status_msg = "Bloqué (403)" if "403" in str(e) else "Erreur"
                    cooldown_mins = 30 if "403" in str(e) else 0
                    updateHealth("vinted", status_msg, str(e), cooldown_mins=cooldown_mins)
                    vintedAds = []
            else:
                vintedAds = []
            
            # Vinted et LBC retournent déjà des objets ScrapedItem typés avec l'attribut site défini
            allAds = lbcAds + vintedAds
                
            newFinds = 0
            conn = getDbConnection()
            cursor = conn.cursor()
            
            for ad in allAds:
                # Filtrage par le prix max
                if ad.price > maxPrice:
                    continue
                    
                # Détection et chargement forcé de la description LBC si le prix est suspect (< 40% du prix max)
                is_suspicious_price = maxPrice is not None and ad.price < (0.4 * maxPrice)
                if is_suspicious_price and ad.site == "leboncoin" and not ad.description:
                    logger.info("Prix suspect LBC détecté (%s€). Chargement de la description pour vérification...", ad.price)
                    ad.description = await fetchLbcDescription(ad.url, browser)
                    
                # 1. Exclusion automatique du matériel HS / panne
                if ad.isBroken():
                    logger.warning("[Filtre HS/Boîte] Annonce de matériel défectueux ou emballage ignorée : '%s'", ad.title)
                    continue
    
                # 1b. Exclusion des annonces contenant des mots bannis (PC complet, config, laptops, CPU...)
                titleLower = ad.title.lower()
                queryLower = keywords.lower()
                bannedWords = [
                    "pc", "ordinateur", "setup", "config", "tour", "unite centrale", "unité centrale", 
                    "complet", "laptop", "portable", "bureautique", "génération", "generation",
                    "i3", "i5", "i7", "i9", "ryzen 3", "ryzen 5", "ryzen 7", "ryzen 9",
                    # Accessoires (à exclure sauf si explicitement recherchés)
                    "ventirad", "cooler", "ventilateur", "ventilador", "fan", "disipador", "dissipatore", 
                    "support", "suporte", "bracket", "holder", "watercooling", "heatsink", "dissipateur",
                    "backplate", "ventola", "kühler", "kuhler", "lüfter", "lufter", "ventilatore",
                    "radiateur", "radiador", "waterblock", "water block", "koeler", "koelers",
                    # Logiciels / Guides / CD
                    "dvd", "driver", "drivers", "manual", "manuel", "cd-rom", "cdrom",
                    # Réparations / Pannes à l'étranger
                    "arreglar", "reparar", "rot", "defekt", "defective", "broken"
                ]
                
                isBanned = False
                for word in bannedWords:
                    # Si le mot banni est dans le titre ET n'était pas recherché par l'utilisateur
                    if word in titleLower and word not in queryLower:
                        if word == "pc":
                            # Pour "pc" (mot entier uniquement) : évite de bloquer "pcie", "pci" etc.
                            paddedTitle = f" {titleLower} "
                            if " pc " in paddedTitle:
                                isBanned = True
                                break
                        else:
                            isBanned = True
                            break
                            
                if isBanned:
                    logger.warning("[Filtre] Annonce contenant un mot banni (%s) ignorée : '%s'", word, ad.title)
                    continue
    
                # 1bb. Détection spécifique des boîtes / emballages vides (multi-langues)
                boxWords = ["boite", "boîte", "box", "caja", "scatolo", "scatola", "karton", "ovp", "vacia", "vacía", "empty", "caixa"]
                isBox = False
                for word in boxWords:
                    if word in titleLower and word not in queryLower:
                        possessionWords = ["avec", "dans sa", "dans son", "with", "in", "con", "mit"]
                        if not any(posWord in titleLower for posWord in possessionWords):
                            isBox = True
                            break
                if isBox:
                    logger.warning("[Filtre Boîte] Annonce d'emballage vide suspectée ignorée : '%s'", ad.title)
                    continue
    
                # 1c. Vérification de la pertinence de la catégorie du composant (Soft Match)
                if not checkTitleRelevance(titleLower, queryLower):
                    logger.warning("[Filtre Catégorie] Annonce exclue car hors-sujet : '%s'", ad.title)
                    continue
    
                # 2. Détection des doublons en pur SQL
                cursor.execute("SELECT 1 FROM products WHERE externalId = ?", (ad.externalId,))
                if cursor.fetchone():
                    continue
                    
                # 3. Formatage et envoi de l'embed riche sur Discord
                embedPayload = ad.toDiscordEmbed(maxPrice, keywords)
                msgId = sendDiscordNotification(DISCORD_WEBHOOK_URL, embedPayload)
                
                # 4. Enregistrement en base de données avec le message ID Discord
                notifiedAtStr = datetime.utcnow().isoformat()
                cursor.execute("""
                    INSERT INTO products 
                    (watchlistId, site, externalId, title, price, url, imageUrl, publishedAt, notifiedAt, discordMessageId)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    itemId,
                    ad.site,
                    ad.externalId,
                    ad.title,
                    ad.price,
                    ad.url,
                    ad.imageUrl,
                    ad.publishedAt,
                    notifiedAtStr,
                    msgId
                ))
                conn.commit()
                
                newFinds += 1
                await asyncio.sleep(randint(1, 5)) # Pause anti-rate-limit Discord
                
            conn.close()
            logger.info("Terminé. %s nouvelles annonces sous le prix max.", newFinds)
            
            # Nettoyage des anciens messages Discord après chaque recherche
            cleanupOldDiscordMessages()
            
            await asyncio.sleep(5)
            
    logger.info("Fin du cycle de scan global.")

async def runPeriodicScans():
    while True:
        try:
            await runScan()
        except Exception as e:
            logger.exception("Erreur critique dans runPeriodicScans : %s", e, exc_info=True)
        await asyncio.sleep(60*10)  # Pause de 10 minutes // sinon BAN 

@app.get("/health")
def getHealth():
    return apiResponse(True, data=SCRAPER_HEALTH)

@app.get("/watchlist")
def getWatchlist():
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, keywords, maxPrice, category, enabled FROM watchlist")
    rows = cursor.fetchall()
    conn.close()
    watchlist = [
        {"id": r[0], "keywords": r[1], "maxPrice": r[2], "category": r[3], "enabled": bool(r[4])}
        for r in rows
    ]
    return apiResponse(True, data=watchlist)

@app.post("/watchlist", dependencies=[Depends(verifyApiKey)])
def addToWatchlist(data: WatchlistCreate):
    conn = getDbConnection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO watchlist (keywords, maxPrice, category) VALUES (?, ?, ?)",
            (data.keywords, data.maxPrice, data.category)
        )
        conn.commit()
        itemId = cursor.lastrowid
        watchlist_item = {
            "id": itemId,
            "keywords": data.keywords,
            "maxPrice": data.maxPrice,
            "category": data.category,
            "enabled": True
        }
        return apiResponse(True, data=watchlist_item)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.patch("/watchlist/{itemId}/toggle", dependencies=[Depends(verifyApiKey)])
def toggleWatchlistItem(itemId: int):
    conn = getDbConnection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT enabled FROM watchlist WHERE id = ?", (itemId,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        new_status = 1 - row[0]
        cursor.execute("UPDATE watchlist SET enabled = ? WHERE id = ?", (new_status, itemId))
        conn.commit()
        return apiResponse(True, data={"itemId": itemId, "enabled": bool(new_status)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.put("/watchlist/{itemId}", dependencies=[Depends(verifyApiKey)])
def updateWatchlistItem(itemId: int, data: WatchlistUpdate):
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM watchlist WHERE id = ?", (itemId,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")
        
    try:
        cursor.execute(
            "UPDATE watchlist SET keywords = ?, maxPrice = ?, category = ?, enabled = ? WHERE id = ?",
            (data.keywords, data.maxPrice, data.category, int(data.enabled), itemId)
        )
        conn.commit()
        return apiResponse(True, data={
            "id": itemId,
            "keywords": data.keywords,
            "maxPrice": data.maxPrice,
            "category": data.category,
            "enabled": data.enabled
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/watchlist/{itemId}", dependencies=[Depends(verifyApiKey)])
def deleteFromWatchlist(itemId: int):
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM watchlist WHERE id = ?", (itemId,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")
        
    # Purger les notifications Discord associées en premier
    cursor.execute("SELECT discordMessageId FROM products WHERE watchlistId = ? AND discordMessageId IS NOT NULL", (itemId,))
    rows = cursor.fetchall()
    if rows and DISCORD_WEBHOOK_URL:
        logger.info("🗑️ Suppression automatique de %s messages Discord suite à la suppression de la recherche %s", len(rows), itemId)
        for (msg_id,) in rows:
            deleteDiscordMessage(DISCORD_WEBHOOK_URL, msg_id)
            import time
            time.sleep(0.2)
            
    cursor.execute("DELETE FROM products WHERE watchlistId = ?", (itemId,))
    cursor.execute("DELETE FROM watchlist WHERE id = ?", (itemId,))
    conn.commit()
    conn.close()
    return apiResponse(True, data={"itemId": itemId})

@app.post("/watchlist/{itemId}/purgeDiscord", dependencies=[Depends(verifyApiKey)])
def purgeDiscordNotifications(itemId: int):
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM watchlist WHERE id = ?", (itemId,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")
        
    cursor.execute("SELECT id, discordMessageId FROM products WHERE watchlistId = ? AND discordMessageId IS NOT NULL", (itemId,))
    rows = cursor.fetchall()
    
    deleted_count = 0
    if rows and DISCORD_WEBHOOK_URL:
        logger.info("🗑️ Purge manuelle de %s messages Discord pour la recherche %s", len(rows), itemId)
        for db_id, msg_id in rows:
            if deleteDiscordMessage(DISCORD_WEBHOOK_URL, msg_id):
                deleted_count += 1
            cursor.execute("UPDATE products SET discordMessageId = NULL WHERE id = ?", (db_id,))
            import time
            time.sleep(0.2)
        conn.commit()
        
    conn.close()
    return apiResponse(True, data={"itemId": itemId, "deleted_count": deleted_count})

@app.get("/products")
def getProducts():
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.watchlistId, p.site, p.externalId, p.title, p.price, p.url, p.imageUrl, p.publishedAt, p.notifiedAt, w.keywords
        FROM products p
        LEFT JOIN watchlist w ON p.watchlistId = w.id
        ORDER BY p.notifiedAt DESC LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()
    products = [
        {
            "id": r[0],
            "watchlistId": r[1],
            "site": r[2],
            "externalId": r[3],
            "title": r[4],
            "price": r[5],
            "url": r[6],
            "imageUrl": r[7],
            "publishedAt": r[8],
            "notifiedAt": r[9],
            "query": r[10] or "Recherche inconnue"
        }
        for r in rows
    ]
    return apiResponse(True, data=products)

@app.post("/purgeDB", dependencies=[Depends(verifyApiKey)])
def purgeDatabase():
    try:
        deleteDB()
        return apiResponse(True, data={"status": "purged"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scan", dependencies=[Depends(verifyApiKey)])
def triggerManualScan(background_tasks: BackgroundTasks):
    background_tasks.add_task(runScan, force=True)
    return apiResponse(True, data={"status": "scan_started"})

if __name__ == "__main__":
    env_type = os.environ.get("ENVIRONEMENT_TYPE", "")
    log_level = "critical" if env_type == "production" else "info"
    is_reload = env_type != "production"
    
    if env_type != "production":
        logger.info("Démarrage du serveur d'API LBCBot...")
        
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=is_reload, log_level=log_level)
