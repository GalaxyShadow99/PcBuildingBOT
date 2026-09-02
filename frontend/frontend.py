import json
import os
import urllib.error
import urllib.request
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

# Chargement du fichier .env pour le développement local
load_dotenv()

app = Flask(__name__)

# Chargement de la clé secrète Flask
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecretkeyforlbcbot")

# Récupération de l'URL du backend et de la clé secrète de l'API
BACKEND_API_URL = os.environ.get("BACKEND_API_URL", "")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")
UI_USERNAME = os.environ.get("UI_USERNAME", "")
UI_PASSWORD = os.environ.get("UI_PASSWORD", "")

if not BACKEND_API_URL:
    raise ValueError("BACKEND_API_URL must be set in the environment variables")
if not UI_USERNAME or not UI_PASSWORD:
    raise ValueError("UI_USERNAME and UI_PASSWORD must be set for authentication")
if not API_SECRET_KEY:
    raise ValueError("API_SECRET_KEY is not set")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('loggedin'):
            return redirect(url_for('login', mess="notLoggedIn"))
        return f(*args, **kwargs)
    return decorated_function

def apiCall(method: str, path: str, payload: dict = None):
    """Effectue un appel API HTTP vers le backend en transmettant la clé X-API-Key dans les Headers."""
    url = f"{BACKEND_API_URL}{path}"
    
    data = None
    headers = {}
    
    if method in ["POST", "DELETE", "PATCH", "PUT"] and API_SECRET_KEY:
        headers["X-API-Key"] = API_SECRET_KEY
        
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except Exception as e:
        return 500, {"success": False, "error": str(e)}

@app.context_processor
def inject_health():
    health = {
        "leboncoin": {"status": "Inconnu", "last_scrape": None, "error": None},
        "vinted": {"status": "Inconnu", "last_scrape": None, "error": None}
    }
    status_h, res_h = apiCall("GET", "/health")
    if status_h == 200 and isinstance(res_h, dict) and res_h.get("success"):
        health = res_h.get("data", {})
    return dict(health=health)

@app.route("/api/health")
def apiHealthProxy():
    status_h, res_h = apiCall("GET", "/health")
    if status_h == 200 and isinstance(res_h, dict):
        return jsonify(res_h.get("data", {}))
    return jsonify({"leboncoin": {"status": "Erreur"}, "vinted": {"status": "Erreur"}})

@app.route("/")
@login_required
def index():
    products = []
    status, res = apiCall("GET", "/products")
    if status == 200 and isinstance(res, dict) and res.get("success"):
        products = res.get("data", [])
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Impossible de récupérer les annonces : {error_msg}", "danger")
        
    return render_template("index.html", products=products)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == UI_USERNAME and password == UI_PASSWORD:
            flash("Connexion réussie !", "success")
            session['loggedin'] = True
            return redirect(url_for("index"))
        else:
            flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")
            return redirect(url_for("login"))
    elif request.method == "GET":
        request_mess = request.args.get("mess")
        if request_mess == "notLoggedIn":
            flash("Cette application est privée et nécessite une connexion", "warning")
        return render_template("login.html")
    else:
        flash("Méthode de requête non autorisée.", "danger")

@app.route("/logout")
def logout():
    session.pop('loggedin', None)
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("login"))



@app.route("/watchlist")
@login_required
def watchlistView():
    watchlist = []
    presets = {}
    
    status, res = apiCall("GET", "/watchlist")
    if status == 200 and isinstance(res, dict) and res.get("success"):
        watchlist = res.get("data", [])
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Impossible de récupérer la watchlist : {error_msg}", "danger")
        
    p_status, p_res = apiCall("GET", "/banned-words/presets")
    if p_status == 200 and isinstance(p_res, dict) and p_res.get("success"):
        presets = p_res.get("data", {})
        
    return render_template("watchlist.html", watchlist=watchlist, presets=presets)

@app.route("/watchlist/add", methods=["POST"])
@login_required
def addWatchlist():
    keywords = request.form.get("keywords")
    maxPrice = request.form.get("max_price")
    category = request.form.get("category", 15)
    useDefaultBannedWords = request.form.get("use_default_banned_words") == "on"
    raw_custom_words = request.form.get("custom_banned_words", "")
    customBannedWords = [w.strip() for w in raw_custom_words.split(",") if w.strip()]
    
    if not keywords or not maxPrice:
        flash("Veuillez renseigner tous les champs obligatoires.", "warning")
        return redirect(url_for("watchlistView"))
        
    payload = {
        "keywords": keywords,
        "maxPrice": float(maxPrice),
        "category": int(category),
        "useDefaultBannedWords": useDefaultBannedWords,
        "customBannedWords": customBannedWords
    }
    
    status, res = apiCall("POST", "/watchlist", payload)
    if status == 200 and isinstance(res, dict) and res.get("success"):
        flash(f"Recherche '{keywords}' ajoutée à la surveillance !", "success")
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Échec de l'ajout : {error_msg}", "danger")
        
    return redirect(url_for("watchlistView"))

@app.route("/watchlist/delete/<int:itemId>", methods=["POST"])
@login_required
def deleteWatchlist(itemId):
    status, res = apiCall("DELETE", f"/watchlist/{itemId}")
    if status == 200 and isinstance(res, dict) and res.get("success"):
        flash("Recherche supprimée avec succès.", "success")
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Échec de la suppression : {error_msg}", "danger")
        
    return redirect(url_for("watchlistView"))

@app.route("/watchlist/edit/<int:itemId>", methods=["POST"])
@login_required
def editWatchlist(itemId):
    keywords = request.form.get("keywords")
    maxPrice = request.form.get("max_price")
    category = request.form.get("category", 15)
    enabled = request.form.get("enabled") == "on"
    useDefaultBannedWords = request.form.get("use_default_banned_words") == "on"
    raw_custom_words = request.form.get("custom_banned_words", "")
    customBannedWords = [w.strip() for w in raw_custom_words.split(",") if w.strip()]
    
    if not keywords or not maxPrice:
        flash("Veuillez remplir tous les champs obligatoires.", "warning")
        return redirect(url_for("watchlistView"))
        
    payload = {
        "keywords": keywords,
        "maxPrice": float(maxPrice),
        "category": int(category),
        "enabled": enabled,
        "useDefaultBannedWords": useDefaultBannedWords,
        "customBannedWords": customBannedWords
    }
    
    status, res = apiCall("PUT", f"/watchlist/{itemId}", payload)
    if status == 200 and isinstance(res, dict) and res.get("success"):
        flash(f"Recherche '{keywords}' modifiée avec succès !", "success")
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Échec de la modification : {error_msg}", "danger")
        
    return redirect(url_for("watchlistView"))

@app.route("/watchlist/purge-discord/<int:itemId>", methods=["POST"])
@login_required
def purgeDiscordWatchlist(itemId):
    status, res = apiCall("POST", f"/watchlist/{itemId}/purgeDiscord")
    if status == 200 and isinstance(res, dict) and res.get("success"):
        deleted = res.get("data", {}).get("deleted_count", 0)
        flash(f"Purge effectuée : {deleted} messages Discord supprimés du canal.", "success")
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Échec de la purge Discord : {error_msg}", "danger")
        
    return redirect(url_for("watchlistView"))

@app.route("/watchlist/toggle/<int:itemId>", methods=["POST"])
@login_required
def toggleWatchlist(itemId):
    status, res = apiCall("PATCH", f"/watchlist/{itemId}/toggle")
    if status == 200 and isinstance(res, dict) and res.get("success"):
        enabled = res.get("data", {}).get("enabled", False)
        status_str = "activée" if enabled else "désactivée"
        flash(f"Surveillance {status_str} avec succès.", "success")
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Échec de l'activation/désactivation : {error_msg}", "danger")
        
    return redirect(url_for("watchlistView"))

@app.route("/scan", methods=["POST"])
@login_required
def triggerScan():
    status, res = apiCall("POST", "/scan")
    if status == 200 and isinstance(res, dict) and res.get("success"):
        flash("Scan manuel déclenché en tâche de fond !", "info")
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Erreur lors du lancement : {error_msg}", "danger")
        
    return redirect(url_for("index"))

@app.route("/purgeDB", methods=["POST"])
@login_required
def purgeDB():
    status, res = apiCall("POST", "/purgeDB")
    if status == 200 and isinstance(res, dict) and res.get("success"):
        flash("Base de données effacée avec succès.", "success")
    else:
        error_msg = res.get("error", "Erreur inconnue") if isinstance(res, dict) else str(res)
        flash(f"Erreur lors de la purge : {error_msg}", "danger")
    return redirect(url_for("index"))

@app.errorhandler(404)
def page_not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(403)
def access_forbidden(e):
    return render_template("errors/403.html"), 403

@app.errorhandler(500)
def internal_server_error(e):
    return render_template("errors/500.html"), 500

if __name__ == "__main__":
    env_type = os.environ.get("ENVIRONEMENT_TYPE", "")
    is_prod = env_type == "production"
    
    if is_prod:
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        
    app.run(host="0.0.0.0", port=5000, debug=not is_prod)
