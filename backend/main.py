from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from random import randint
from typing import Any

import uvicorn
from database import deleteDB, getDbConnection, initDb
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from filters import checkHardwareModelCompatibility, checkTitleRelevance
from logger import logger
from notifier import deleteDiscordMessage, sendDiscordNotification
from pydantic import BaseModel
from scrapers import VintedScraper
from scrapers.item import ScrapedItem
from services.ai_analyzer import analyzeDealWithOllama
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    initDb()
    # Lancement de la tâche de fond de surveillance périodique
    task_scan = asyncio.create_task(runPeriodicScans())
    task_health = asyncio.create_task(runPeriodicHealthCheck())
    yield
    task_scan.cancel()
    task_health.cancel()

app = FastAPI(title="LBCBot API", lifespan=lifespan)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")
MAX_PAGES_PER_SITE = int(os.environ.get("MAX_PAGES_PER_SITE", os.environ.get("MAX_PAGES", "1")))
MAX_VINTED_ITEMS = int(os.environ.get("MAX_VINTED_ITEMS", "30"))
if not MAX_PAGES_PER_SITE:
    logger.fatal("MAX_PAGES_PER_SITE doit être un entier positif. Valeur actuelle : %s", MAX_PAGES_PER_SITE)
    sys.exit(1)
if not API_SECRET_KEY:
    logger.fatal("Aucune clé API définie. Les appels POST/DELETE seront refusés.")
    sys.exit(1)
if not DISCORD_WEBHOOK_URL:
    logger.fatal("Aucun webhook Discord défini. Les notifications ne seront pas envoyées.")
    sys.exit(1)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verifyApiKey(key: str = Depends(api_key_header)):
    if not API_SECRET_KEY:
        raise HTTPException(
                    status_code=401,
                    detail="Clé API non configurée."
                )
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

async def updateHealthAuto():
    """
    Effectue un ping de test réseau sur Vinted.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    # 1. Ping Vinted uniquement s'il n'est pas OK
    if SCRAPER_HEALTH["vinted"]["status"] != "OK":
        logger.info("[Ping Test] Test de connexion réseau en cours sur Vinted...")
        try:
            import httpx
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=5) as client:
                res = await client.get("https://www.vinted.fr")
                if res.status_code == 200:
                    updateHealth("vinted", "OK")
                    logger.info("[Ping Test] Vinted accessible (HTTP 200) ! Statut rétabli à OK.")
                elif res.status_code == 403:
                    updateHealth("vinted", "Bloqué (403)", "Code HTTP 403 sur le ping de test", cooldown_mins=30)
                    logger.warning("[Ping Test] Vinted toujours bloqué (HTTP 403). Cooldown maintenu.")
        except Exception as e:
            logger.error("[Ping Test] Échec du ping Vinted : %s", e)

async def runPeriodicHealthCheck():
    """Tâche de fond qui teste la santé des scrapers toutes les 5 minutes."""
    while True:
        try:
            await updateHealthAuto()
        except Exception as e:
            logger.error("Erreur dans le healthcheck automatique : %s", e)
        await asyncio.sleep(5 * 60)

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
    useDefaultBannedWords: bool = True
    customBannedWords: list[str] = []

class WatchlistUpdate(BaseModel):
    keywords: str
    maxPrice: float
    category: int = 15
    enabled: bool = True
    useDefaultBannedWords: bool = True
    customBannedWords: list[str] = []

# Instanciation des scrapers
vintedScraper = VintedScraper()

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
    logger.debug("Début du cycle de scan global...")
    start_time = time.perf_counter()
    # Récupération des recherches actives en unpacking de tuples
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, keywords, maxPrice, category, useDefaultBannedWords FROM watchlist WHERE enabled = 1")
    activeItems = cursor.fetchall()
    
    # Récupération des mots bannis globaux/par défaut
    cursor.execute("SELECT word FROM default_banned_words")
    defaultBannedWords = [row[0].lower() for row in cursor.fetchall()]
    conn.close()
    
    if not activeItems:
        logger.debug("Aucune recherche active dans la watchlist.")
        return
     
    for itemId, keywords, maxPrice, category, useDefaultBannedWords in activeItems:
        logger.debug("Scan de '%s' (max %s€)...", keywords, maxPrice)
        
        # Récupération des mots bannis spécifiques pour cette recherche
        conn = getDbConnection()
        cursor = conn.cursor()
        cursor.execute("SELECT word FROM watchlist_banned_words WHERE watchlistId = ?", (itemId,))
        customBannedWords = [row[0].lower() for row in cursor.fetchall()]
        conn.close()
        
        # Construction de la banlist finale pour cet élément
        bannedWords = list(customBannedWords)
        if useDefaultBannedWords:
            bannedWords.extend(defaultBannedWords)

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
                vintedAds = await vintedScraper.scrape(keywords, maxPrice=maxPrice, maxPages=MAX_PAGES_PER_SITE, maxItems=MAX_VINTED_ITEMS)
                updateHealth("vinted", "OK")
            except Exception as e:
                logger.error("[Scan Vinted] Échec : %s", e)
                status_msg = "Bloqué (403)" if "403" in str(e) else "Erreur"
                cooldown_mins = 30 if "403" in str(e) else 0
                updateHealth("vinted", status_msg, str(e), cooldown_mins=cooldown_mins)
                vintedAds = []
        else:
            vintedAds = []
        
        allAds = vintedAds
            
        newFinds = 0
        conn = getDbConnection()
        cursor = conn.cursor()
        
        for ad in allAds:
            # Filtrage par le prix max
            if maxPrice and ad.price > maxPrice:
                continue
                    
            # 1. Exclusion automatique du matériel HS / panne
            if ad.isBroken():
                logger.debug("[Filtre HS/Boîte] Annonce de matériel défectueux ou emballage ignorée : '%s'", ad.title)
                continue

            # 1b. Exclusion dynamique via banlist (globale + spécifique)
            titleLower = ad.title.lower()
            queryLower = keywords.lower()
            
            banned_match = None
            for word in bannedWords:
                wordLower = word.lower().strip()
                if not wordLower:
                    continue
                # Si le mot banni est présent et n'était pas recherché par l'utilisateur
                if wordLower in titleLower and wordLower not in queryLower:
                    banned_match = wordLower
                    break
                        
            if banned_match:
                logger.debug("[Filtre Banword] Annonce contenant le mot banni (%s) ignorée : '%s'", banned_match, ad.title)
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
                logger.debug("[Filtre Boîte] Annonce d'emballage vide suspectée ignorée : '%s'", ad.title)
                continue

            # 1c. Vérification de la pertinence de la catégorie du composant (Soft Match)
            if not checkTitleRelevance(titleLower, queryLower):
                logger.debug("[Filtre Catégorie] Annonce exclue car hors-sujet : '%s'", ad.title)
                continue

            # 1d. Vérification déterministe des modèles (Chipsets H610/B85, DDR3/DDR4, SODIMM)
            if not checkHardwareModelCompatibility(titleLower, queryLower, descriptionLower=ad.description or ""):
                logger.debug("[Filtre Modèle/Chipset] Annonce exclue car modèle/chipset non correspondant : '%s'", ad.title)
                continue

            # 2. Détection des doublons et des annonces bannies/déjà traitées en SQL
            cursor.execute("SELECT 1 FROM annonce_banlist WHERE externalId = ?", (ad.externalId,))
            if cursor.fetchone():
                logger.debug("[Filtre Banlist Annonce] Annonce déjà traitée/bannie ignorée : '%s'", ad.title)
                continue

            cursor.execute("SELECT 1 FROM products WHERE externalId = ?", (ad.externalId,))
            if cursor.fetchone():
                continue

            if getattr(ad, "isSold", False):
                logger.debug("[Filtre Dispo] Annonce déjà vendue / indisponible sur Vinted, ignorée : '%s'", ad.title)
                continue
                
            # 3. Analyse IA ciblée par Ollama/Llama (avec filtrage binaire is_good_deal)
            logger.debug("[Analyse IA] Interrogation de llama-server pour '%s' (%s€)...", ad.title, ad.price)
            try:
                aiAnalysis, aiIsGoodDeal = await analyzeDealWithOllama(
                    title=ad.title,
                    price=ad.price,
                    maxPrice=maxPrice,
                    keywords=keywords,
                    description=ad.description
                )
            except Exception as ai_err:
                logger.error("[Analyse IA] Exception imprévue lors de l'appel LLM : %s", ai_err)
                aiAnalysis, aiIsGoodDeal = None, None
            
            # Si l'IA refuse (is_good_deal = False) OU si LLM est en erreur (aiIsGoodDeal is None), on bloque la notification Discord
            # et on enregistre l'externalId dans annonce_banlist pour ne plus JAMAIS ré-analyser cette ancienne annonce !
            if aiIsGoodDeal is not True:
                logger.info("[IA Refusé] Annonce '%s' (%s €) | URL: %s | Raison: %s", ad.title, ad.price, ad.url, aiAnalysis or "Annonce refusée par l'IA")
                bannedAtStr = datetime.utcnow().isoformat()
                cursor.execute(
                    "INSERT OR IGNORE INTO annonce_banlist (site, externalId, bannedAt) VALUES (?, ?, ?)",
                    (ad.site, ad.externalId, bannedAtStr)
                )
                conn.commit()
                continue
            
            # 4. Formatage et envoi de l'embed riche sur Discord
            embedPayload = ad.toDiscordEmbed(maxPrice, keywords, aiAnalysis=aiAnalysis)
            msgId = sendDiscordNotification(DISCORD_WEBHOOK_URL, embedPayload)
            logger.info("[Notification Discord Envoyée] '%s' (%s €) | URL: %s | Résumé IA: %s", ad.title, ad.price, ad.url, aiAnalysis or "Aucun résumé")
            
            # 5. Enregistrement en base de données avec le message ID Discord et la description complète
            notifiedAtStr = datetime.utcnow().isoformat()
            cursor.execute("""
                INSERT INTO products 
                (watchlistId, site, externalId, title, price, url, imageUrl, description, publishedAt, notifiedAt, discordMessageId, isSold)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                itemId,
                ad.site,
                ad.externalId,
                ad.title,
                ad.price,
                ad.url,
                ad.imageUrl,
                ad.description,
                ad.publishedAt,
                notifiedAtStr,
                msgId,
                1 if getattr(ad, "isSold", False) else 0
            ))
            conn.commit()
            
            newFinds += 1
            await asyncio.sleep(randint(1, 5)) # Pause anti-rate-limit Discord
            
        conn.close()
        logger.debug("Terminé. %s nouvelles annonces sous le prix max.", newFinds)
        
        # Nettoyage des anciens messages Discord après chaque recherche
        cleanupOldDiscordMessages()
        
        await asyncio.sleep(5)
    end_time = time.perf_counter()
    logger.info(f"Fin du cycle de scan global | Durée : {end_time - start_time:0.4f} sec ")

async def runPeriodicScans():
    while True:
        try:
            await runScan()
        except Exception as e:
            logger.exception("Erreur critique dans runPeriodicScans : %s", e, exc_info=True)
        await asyncio.sleep(60*2) # pause de 2 minutes 

@app.get("/health")
def getHealth():
    """Endpoint GET retournant l'état de santé et de cooldown des scrapers."""
    return apiResponse(True, data=SCRAPER_HEALTH)

@app.get("/banned-words/presets")
def getBannedWordsPresets():
    """Endpoint GET retournant les mots bannis par défaut catégorisés."""
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT word, category FROM default_banned_words")
    rows = cursor.fetchall()
    conn.close()
    
    presets = {}
    for word, category in rows:
        if category not in presets:
            presets[category] = []
        presets[category].append(word)
        
    return apiResponse(True, data=presets)

@app.get("/watchlist")
def getWatchlist():
    """Endpoint GET retournant la liste complète des recherches sous surveillance."""
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, keywords, maxPrice, category, enabled, useDefaultBannedWords FROM watchlist")
    rows = cursor.fetchall()
    
    watchlist = []
    for r in rows:
        itemId = r[0]
        cursor.execute("SELECT word FROM watchlist_banned_words WHERE watchlistId = ?", (itemId,))
        custom_words = [w[0] for w in cursor.fetchall()]
        watchlist.append({
            "id": itemId,
            "keywords": r[1],
            "maxPrice": r[2],
            "category": r[3],
            "enabled": bool(r[4]),
            "useDefaultBannedWords": bool(r[5]),
            "customBannedWords": custom_words
        })
        
    conn.close()
    return apiResponse(True, data=watchlist)

@app.post("/watchlist", dependencies=[Depends(verifyApiKey)])
def addToWatchlist(data: WatchlistCreate):
    """Enregistre un nouvel élément dans la watchlist."""
    conn = getDbConnection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO watchlist (keywords, maxPrice, category, useDefaultBannedWords) VALUES (?, ?, ?, ?)",
            (data.keywords, data.maxPrice, data.category, int(data.useDefaultBannedWords))
        )
        conn.commit()
        itemId = cursor.lastrowid
        
        # Enregistrement des mots bannis spécifiques
        if data.customBannedWords:
            cursor.executemany(
                "INSERT OR IGNORE INTO watchlist_banned_words (watchlistId, word) VALUES (?, ?)",
                [(itemId, word.strip()) for word in data.customBannedWords if word.strip()]
            )
            conn.commit()
            
        watchlist_item = {
            "id": itemId,
            "keywords": data.keywords,
            "maxPrice": data.maxPrice,
            "category": data.category,
            "enabled": True,
            "useDefaultBannedWords": data.useDefaultBannedWords,
            "customBannedWords": [w.strip() for w in data.customBannedWords if w.strip()]
        }
        return apiResponse(True, data=watchlist_item)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.patch("/watchlist/{itemId}/toggle", dependencies=[Depends(verifyApiKey)])
def toggleWatchlistItem(itemId: int):
    """Bascule l'état actif/désactivé d'une recherche dans la watchlist."""
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
    """Met à jour les critères et mots bannis d'une recherche existante."""
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM watchlist WHERE id = ?", (itemId,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")
        
    try:
        cursor.execute(
            "UPDATE watchlist SET keywords = ?, maxPrice = ?, category = ?, enabled = ?, useDefaultBannedWords = ? WHERE id = ?",
            (data.keywords, data.maxPrice, data.category, int(data.enabled), int(data.useDefaultBannedWords), itemId)
        )
        
        # Remplacement complet des mots bannis spécifiques
        cursor.execute("DELETE FROM watchlist_banned_words WHERE watchlistId = ?", (itemId,))
        if data.customBannedWords:
            cursor.executemany(
                "INSERT OR IGNORE INTO watchlist_banned_words (watchlistId, word) VALUES (?, ?)",
                [(itemId, word.strip()) for word in data.customBannedWords if word.strip()]
            )
            
        conn.commit()
        return apiResponse(True, data={
            "id": itemId,
            "keywords": data.keywords,
            "maxPrice": data.maxPrice,
            "category": data.category,
            "enabled": data.enabled,
            "useDefaultBannedWords": data.useDefaultBannedWords,
            "customBannedWords": [w.strip() for w in data.customBannedWords if w.strip()]
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/watchlist/{itemId}", dependencies=[Depends(verifyApiKey)])
async def deleteFromWatchlist(itemId: int):
    """Supprime une recherche de la watchlist et supprime ses notifications Discord."""
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
        logger.info("Suppression automatique de %s messages Discord suite à la suppression de la recherche %s", len(rows), itemId)
        for (msg_id,) in rows:
            deleteDiscordMessage(DISCORD_WEBHOOK_URL, msg_id)
            await asyncio.sleep(randint(1, 3) * 0.8)
            
    cursor.execute("DELETE FROM products WHERE watchlistId = ?", (itemId,))
    cursor.execute("DELETE FROM watchlist WHERE id = ?", (itemId,))
    conn.commit()
    conn.close()
    return apiResponse(True, data={"itemId": itemId})

@app.post("/watchlist/{itemId}/purgeDiscord", dependencies=[Depends(verifyApiKey)])
async def purgeDiscordNotifications(itemId: int):
    """Purge manuellement tous les messages Discord envoyés pour une recherche donnée."""
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
        logger.info("Purge manuelle de %s messages Discord pour la recherche %s", len(rows), itemId)
        for db_id, msg_id in rows:
            if deleteDiscordMessage(DISCORD_WEBHOOK_URL, msg_id):
                deleted_count += 1
            cursor.execute("UPDATE products SET discordMessageId = NULL WHERE id = ?", (db_id,))
            await asyncio.sleep(randint(1, 3) * 0.8)
        conn.commit()
        
    conn.close()
    return apiResponse(True, data={"itemId": itemId, "deleted_count": deleted_count})

@app.get("/products")
def getProducts():
    """Retourne les 50 dernières annonces notifiées conservées en base de données."""
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.watchlistId, p.site, p.externalId, p.title, p.price, p.url, p.imageUrl, p.publishedAt, p.notifiedAt, w.keywords, p.isSold
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
            "query": r[10] or "Recherche inconnue",
            "isSold": bool(r[11]) if len(r) > 11 and r[11] is not None else False
        }
        for r in rows
    ]
    return apiResponse(True, data=products)

@app.delete("/products/{productId}", dependencies=[Depends(verifyApiKey)])
def deleteProduct(productId: int):
    """Supprime une annonce notifiée et ajoute son ID externe à la banlist."""
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT site, externalId, discordMessageId FROM products WHERE id = ?", (productId,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
        
    site, externalId, msg_id = row
    if msg_id and DISCORD_WEBHOOK_URL:
        deleteDiscordMessage(DISCORD_WEBHOOK_URL, msg_id)
        
    bannedAtStr = datetime.utcnow().isoformat()
    cursor.execute(
        "INSERT OR IGNORE INTO annonce_banlist (site, externalId, bannedAt) VALUES (?, ?, ?)",
        (site, externalId, bannedAtStr)
    )
    cursor.execute("DELETE FROM products WHERE id = ?", (productId,))
    conn.commit()
    conn.close()
    return apiResponse(True, data={"productId": productId})

@app.post("/products/{productId}/check-availability", dependencies=[Depends(verifyApiKey)])
async def checkProductAvailability(productId: int):
    """Vérifie directement sur Vinted si l'annonce est toujours disponible ou vendue."""
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, price, url, site, externalId FROM products WHERE id = ?", (productId,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
        
    p_id, title, price, url, site, externalId = row
    conn.close()

    scraped_item = ScrapedItem(
        externalId=externalId,
        title=title,
        price=price,
        url=url,
        site=site
    )

    import httpx
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
        await scraped_item.fetchDescription(client)

    is_sold = scraped_item.isSold

    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET isSold = ? WHERE id = ?", (1 if is_sold else 0, productId))
    conn.commit()
    conn.close()

    return apiResponse(True, data={
        "productId": productId,
        "isSold": is_sold,
        "statusText": "Vendu / Plus dispo" if is_sold else "Disponible"
    })

@app.post("/products/{productId}/reanalyze", dependencies=[Depends(verifyApiKey)])
async def reanalyzeProductWithAI(productId: int):
    """Réévalue une annonce enregistrée via l'analyseur décisionnel LLM Ollama."""
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.title, p.price, p.url, p.site, p.description, w.keywords, w.maxPrice 
        FROM products p 
        LEFT JOIN watchlist w ON p.watchlistId = w.id 
        WHERE p.id = ?
    """, (productId,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
        
    p_id, title, price, url, site, description, keywords, maxPrice = row
    conn.close()
    
    # Appel asynchrone à Ollama pour réévaluer l'annonce avec sa description sauvegardée
    analysis, is_good_deal = await analyzeDealWithOllama(
        title=title,
        price=price,
        maxPrice=maxPrice or 0.0,
        keywords=keywords or title,
        description=description
    )
    return apiResponse(True, data={
        "productId": productId,
        "is_good_deal": is_good_deal,
        "analysis": analysis
    })

@app.post("/purgeDB", dependencies=[Depends(verifyApiKey)])
def purgeDatabase():
    """Purge l'intégralité de la base de données (watchlist et annonces)."""
    try:
        deleteDB()
        return apiResponse(True, data={"status": "purged"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scan", dependencies=[Depends(verifyApiKey)])
def triggerManualScan(background_tasks: BackgroundTasks):
    """Déclenche un cycle de scan immédiat en arrière-plan."""
    background_tasks.add_task(runScan, force=True)
    return apiResponse(True, data={"status": "scan_started"})

@app.get("/")
def root():
    """Endpoint racine confirmant le bon fonctionnement de l'API."""
    return apiResponse(True, data={"message": "API is running."})

if __name__ == "__main__":
    env_type = os.environ.get("ENVIRONMENT_TYPE", os.environ.get("ENVIRONEMENT_TYPE", ""))
    log_level = "critical" if env_type == "production" else "info"
    is_reload = env_type != "production"
    
    if env_type != "production":
        logger.info("Démarrage du serveur d'API LBCBot...")
        
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=is_reload, log_level=log_level)
