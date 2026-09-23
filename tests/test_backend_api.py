from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from database import initDb
from main import app, API_SECRET_KEY

initDb()
client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": API_SECRET_KEY}

# 1. GET /
def test_endpoint_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json().get("success") is True

# 2. GET /health
def test_endpoint_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert "vinted" in data.get("data", {})

# 3. GET /banned-words/presets
def test_endpoint_banned_words_presets():
    response = client.get("/banned-words/presets")
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert isinstance(data.get("data"), dict)

# 4. GET /watchlist
def test_endpoint_get_watchlist():
    response = client.get("/watchlist")
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert isinstance(data.get("data"), list)

# 5. POST /watchlist (Create)
def test_endpoint_create_watchlist_item():
    payload = {
        "keywords": "RTX 3070",
        "maxPrice": 300.0,
        "category": 15,
        "useDefaultBannedWords": True,
        "customBannedWords": ["boite", "hs"]
    }
    response = client.post("/watchlist", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert data["data"]["keywords"] == "RTX 3070"
    return data["data"]["id"]

# 6. PATCH /watchlist/{itemId}/toggle
def test_endpoint_toggle_watchlist_item():
    # D'abord créer un item
    item_id = test_endpoint_create_watchlist_item()
    
    response = client.patch(f"/watchlist/{item_id}/toggle", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert data["data"]["enabled"] is False

# 7. PUT /watchlist/{itemId} (Update)
def test_endpoint_update_watchlist_item():
    item_id = test_endpoint_create_watchlist_item()
    
    update_payload = {
        "keywords": "RTX 3070 Ti",
        "maxPrice": 350.0,
        "category": 15,
        "enabled": True,
        "useDefaultBannedWords": True,
        "customBannedWords": ["boite"]
    }
    response = client.put(f"/watchlist/{item_id}", json=update_payload, headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert data["data"]["keywords"] == "RTX 3070 Ti"

# 8. POST /watchlist/{itemId}/purgeDiscord
def test_endpoint_purge_discord():
    item_id = test_endpoint_create_watchlist_item()
    response = client.post(f"/watchlist/{item_id}/purgeDiscord", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json().get("success") is True

# 9. DELETE /watchlist/{itemId}
def test_endpoint_delete_watchlist_item():
    item_id = test_endpoint_create_watchlist_item()
    response = client.delete(f"/watchlist/{item_id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["data"]["itemId"] == item_id

# 10. GET /products
def test_endpoint_get_products():
    response = client.get("/products")
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert isinstance(data.get("data"), list)

# 11. DELETE /products/{productId} (Error 404 test on unexisting product)
def test_endpoint_delete_product_not_found():
    response = client.delete("/products/9999999", headers=AUTH_HEADERS)
    assert response.status_code == 404
    assert response.json().get("success") is False

# 12. POST /products/{productId}/check-availability (Error 404 test)
def test_endpoint_check_availability_not_found():
    response = client.post("/products/9999999/check-availability", headers=AUTH_HEADERS)
    assert response.status_code == 404

# 13. POST /products/{productId}/reanalyze (Error 404 test)
def test_endpoint_reanalyze_product_not_found():
    response = client.post("/products/9999999/reanalyze", headers=AUTH_HEADERS)
    assert response.status_code == 404

# 14. POST /purgeDB
def test_endpoint_purge_db():
    response = client.post("/purgeDB", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "purged"

def test_endpoint_trigger_scan():
    response = client.post("/scan", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "scan_started"
