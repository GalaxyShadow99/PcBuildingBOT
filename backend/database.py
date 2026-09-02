import logging
import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("LBCBot")

DB_PATH = os.environ.get("DATABASE_PATH", "database.db")

# Normalisation automatique du chemin pour éviter les erreurs de dossier de travail (CWD)
if not os.path.isabs(DB_PATH):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if DB_PATH.startswith("./backend/") or DB_PATH.startswith("backend/"):
        project_root = os.path.dirname(current_dir)
        DB_PATH = os.path.abspath(os.path.join(project_root, DB_PATH))
    else:
        DB_PATH = os.path.abspath(os.path.join(current_dir, DB_PATH))

def getDbConnection():
    """Retourne une connexion active SQLite standard (sans row_factory)."""
    return sqlite3.connect(DB_PATH)

def initDb():
    """Initialise la base de données et gère la migration automatique vers camelCase."""
    if os.path.exists(DB_PATH):
        conn = getDbConnection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT max_price FROM watchlist LIMIT 1")
            conn.close()
            os.remove(DB_PATH)
            logger.info("Ancienne base de données snake_case détectée et supprimée pour migration.")
        except sqlite3.OperationalError:
            conn.close()

    conn = getDbConnection()
    cursor = conn.cursor()
    
    # Table watchlist (surveillance)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keywords TEXT NOT NULL,
            maxPrice REAL NOT NULL,
            category INTEGER DEFAULT 15,
            enabled INTEGER DEFAULT 1,
            useDefaultBannedWords INTEGER DEFAULT 1
        )
    """)

    # Table des mots bannis par défaut (globaux) catégorisés
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS default_banned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            category TEXT DEFAULT 'Build-Complet'
        )
    """)

    # Table des mots bannis spécifiques à chaque recherche
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_banned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlistId INTEGER NOT NULL,
            word TEXT NOT NULL,
            FOREIGN KEY (watchlistId) REFERENCES watchlist(id) ON DELETE CASCADE,
            UNIQUE(watchlistId, word)
        )
    """)
    
    # Table products (annonces déjà notifiées)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlistId INTEGER,
            site TEXT NOT NULL,
            externalId TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            url TEXT NOT NULL,
            imageUrl TEXT,
            publishedAt TEXT,
            notifiedAt TEXT NOT NULL,
            discordMessageId TEXT,
            FOREIGN KEY (watchlistId) REFERENCES watchlist(id) ON DELETE CASCADE
        )
    """)
    
    # Migration : Ajout de la colonne discordMessageId si absente
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN discordMessageId TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migration : Ajout de la colonne useDefaultBannedWords si absente
    try:
        cursor.execute("ALTER TABLE watchlist ADD COLUMN useDefaultBannedWords INTEGER DEFAULT 1")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migration : Ajout de la colonne category dans default_banned_words si absente
    try:
        cursor.execute("ALTER TABLE default_banned_words ADD COLUMN category TEXT DEFAULT 'Build-Complet'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Purge des mots génériques trop stricts qui faisaient rater de bonnes annonces
    cursor.execute("DELETE FROM default_banned_words WHERE word IN ('pc', 'i3', 'i5', 'i7', 'i9', 'ryzen 3', 'ryzen 5', 'ryzen 7', 'ryzen 9', 'ordinateur', 'setup', 'config', 'tour', 'laptop', 'portable', 'bureautique', 'computer', 'desktop', 'ordenador', 'portatil', 'portatile')")
    conn.commit()

    # Peuplement initial de la table default_banned_words si vide (FR, EN, DE, ES, IT, NL, PT)
    cursor.execute("SELECT COUNT(*) FROM default_banned_words")
    if cursor.fetchone()[0] == 0:
        categorized_words = [
            # --- Build-Complet / Ordinateurs Entiers (Expressions Stricte Explicites uniquement) ---
            ("unite centrale", "Build-Complet"), ("unité centrale", "Build-Complet"), ("pc complet", "Build-Complet"), 
            ("komplett pc", "Build-Complet"), ("equipo completo", "Build-Complet"), ("pc completo", "Build-Complet"),
            ('laptop', 'Build-Complet'),('notebook', 'Build-Complet'),('portátil', 'Build-Complet'),('portatile', 'Build-Complet'),
            ("ordinateur portable", "Build-Complet"), ("ordenador portátil", "Build-Complet"), ("computer portatile", "Build-Complet"),
            ("ordinateur de bureau", "Build-Complet"), ("ordenador de sobremesa", "Build-Complet"), ("computer desktop", "Build-Complet"),
            ("pc de bureau", "Build-Complet"), ("pc de sobremesa", "Build-Complet"), ("pc da scrivania", "Build-Complet"),
            ("tour pc", "Build-Complet"), ("torre pc", "Build-Complet"), ("pc tower", "Build-Complet"),
            ("config complète", "Build-Complet"), ("config completa", "Build-Complet"), ("komplett konfiguration", "Build-Complet"),
            
            # --- Refroidissement / Ventirads / Watercooling / Accessoires ---
            ("ventirad", "cooling"), ("cooler", "cooling"), ("ventilateur", "cooling"), ("ventilador", "cooling"), ("fan", "cooling"),
            ("disipador", "cooling"), ("dissipatore", "cooling"), ("support", "cooling"), ("suporte", "cooling"), ("bracket", "cooling"),
            ("holder", "cooling"), ("watercooling", "cooling"), ("heatsink", "cooling"), ("dissipateur", "cooling"), ("backplate", "cooling"),
            ("ventola", "cooling"), ("kühler", "cooling"), ("kuhler", "cooling"), ("lüfter", "cooling"), ("lufter", "cooling"),
            ("ventilatore", "cooling"), ("radiateur", "cooling"), ("radiador", "cooling"), ("waterblock", "cooling"), ("water block", "cooling"),
            ("koeler", "cooling"), ("koelers", "cooling"), ("chiller", "cooling"), ("aio", "cooling"),
            ("wasserkühlung", "cooling"), ("wasserkuehlung", "cooling"), ("refrigeracion", "cooling"), ("refrigeración", "cooling"),
            ("raffreddamento", "cooling"), ("koeling", "cooling"), ("befestigung", "cooling"),
            
            # --- RAM Laptop / SODIMM ---
            ("sodimm", "ram_laptop"), ("so-dimm", "ram_laptop"), ("sodim", "ram_laptop"), 
            ("laptop ram", "ram_laptop"), ("notebook ram", "ram_laptop"), ("ram portable", "ram_laptop"),
            
            # --- Matériel Serveur / ECC ---
            ("ecc", "server"), ("registered", "server"), ("rdimm", "server"), ("serveur", "server"), ("server", "server"),
            ("serverram", "server"), ("ecc memory", "server"), ("servidor", "server"), ("serverheugenis", "server"),
            
            # --- Emballages / Boîtes Seules / Vides ---
            ("boite", "packaging"), ("boîte", "packaging"), ("box", "packaging"), ("carton", "packaging"), ("caja", "packaging"),
            ("box only", "packaging"), ("emballage", "packaging"), ("verpakking", "packaging"), ("verpackung", "packaging"),
            ("scatola", "packaging"), ("scatolo", "packaging"), ("caixa", "packaging"), ("karton", "packaging"),
            ("empty box", "packaging"), ("boite vide", "packaging"), ("boîte vide", "packaging"), ("caja vacia", "packaging"),
            ("caja vacía", "packaging"), ("leere verpackung", "packaging"), ("leerkarton", "packaging"), ("ovp", "packaging"),
            
            # --- Matériel HS / Panne / Pièces ---
            ("hs", "broken"), ("panne", "broken"), ("pour pieces", "broken"), ("pour pièces", "broken"),
            ("arreglar", "broken"), ("reparar", "broken"), ("rot", "broken"), ("defekt", "broken"), ("defective", "broken"), ("broken", "broken"),
            ("for parts", "broken"), ("spares", "broken"), ("para piezas", "broken"), ("para repuestos", "broken"),
            ("per parti di ricambio", "broken"), ("defetto", "broken"), ("gusto", "broken"), ("defect", "broken"),
            ("capaciteit defect", "broken"), ("avaria", "broken"), ("estragado", "broken"),
            
            # --- Logiciels / Pilotes / Manuel ---
            ("dvd", "software"), ("driver", "software"), ("drivers", "software"), ("manual", "software"), ("manuel", "software"),
            ("cd-rom", "software"), ("cdrom", "software"), ("anleitung", "software"), ("handbuch", "software"), ("guia", "software"), ("guía", "software")
        ]
        cursor.executemany("INSERT OR IGNORE INTO default_banned_words (word, category) VALUES (?, ?)", categorized_words)
        conn.commit()
        
    conn.commit()
    conn.close()
    logger.info("Base de données SQLite initialisée avec succès (camelCase + Mots Bannis Catégorisés).")


def listItems():
    conn = getDbConnection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, keywords, maxPrice, category, enabled FROM watchlist")
    items = cursor.fetchall()
    conn.close()
    
    print("\n=== WATCHLIST ACTUELLE (Pur SQL & javaCase) ===")
    if not items:
        print("Aucune recherche configurée.")
    for itemId, keywords, maxPrice, category, enabled in items:
        status = "Actif" if enabled == 1 else "Désactivé"
        print(f"[{itemId}] '{keywords}' | Max : {maxPrice}€ | Catégorie : {category} | Statut : {status}")
    print("===============================================\n")

def addItem(keywords, maxPrice, category=15):
    conn = getDbConnection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO watchlist (keywords, maxPrice, category) VALUES (?, ?, ?)",
            (keywords, float(maxPrice), int(category))
        )
        conn.commit()
        print(f"Ajouté à la watchlist : '{keywords}' à max {maxPrice}€")
    except Exception as e:
        print(f"Erreur lors de l'ajout : {e}")
    finally:
        conn.close()

def deleteItem(itemId):
    conn = getDbConnection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT keywords FROM watchlist WHERE id = ?", (int(itemId),))
        row = cursor.fetchone()
        if row:
            keywords = row[0]
            cursor.execute("DELETE FROM watchlist WHERE id = ?", (int(itemId),))
            conn.commit()
            print(f"Supprimé de la watchlist : [{itemId}] '{keywords}'")
        else:
            print(f"Élément avec l'ID {itemId} introuvable.")
    except Exception as e:
        print(f"Erreur lors de la suppression : {e}")
    finally:
        conn.close()

def deleteDB():
    conn = getDbConnection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM products")
        conn.commit()
        cursor.execute("DELETE FROM watchlist")
        conn.commit()

        print("Toutes les annonces / recherches ont été supprimées de la base de données.")
    except Exception as e:
        print(f"Erreur lors de la suppression de la base : {e}")
    finally:
        conn.close()
