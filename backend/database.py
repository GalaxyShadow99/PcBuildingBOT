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
            enabled INTEGER DEFAULT 1
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
        
    conn.commit()
    conn.close()
    logger.info("Base de données SQLite initialisée avec succès (camelCase).")


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
