from unittest.mock import patch
import pytest
from frontend import app, UI_USERNAME, UI_PASSWORD

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'testsecretkey'
    with app.test_client() as client:
        yield client

def test_frontend_login_page_get(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert b"Connexion" in response.data or b"login" in response.data.lower()

def test_frontend_login_success(client):
    response = client.post('/login', data={
        'username': UI_USERNAME,
        'password': UI_PASSWORD
    }, follow_redirects=True)
    assert response.status_code == 200
    # After login, redirects to index or shows logged in content
    with client.session_transaction() as sess:
        assert sess.get('loggedin') is True

def test_frontend_login_failure(client):
    response = client.post('/login', data={
        'username': 'wronguser',
        'password': 'wrongpassword'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"incorrect" in response.data.lower()

def test_frontend_logout(client):
    with client.session_transaction() as sess:
        sess['loggedin'] = True

    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get('loggedin') is None

def test_frontend_protected_index_redirect(client):
    # Unauthenticated access should redirect to /login
    response = client.get('/')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_frontend_api_health_proxy(client):
    mock_health = {"vinted": {"status": "OK"}}
    with patch('frontend.apiCall', return_value=(200, {"success": True, "data": mock_health})):
        response = client.get('/api/health')
        assert response.status_code == 200
        assert response.json.get("vinted", {}).get("status") == "OK"



def test_frontend_docs_route(client):
    with client.session_transaction() as sess:
        sess['loggedin'] = True
    response = client.get('/docs/')
    # 200 if site folder exists or 404/500 depending on build environment
    assert response.status_code in [200, 404]

def test_frontend_404_error_handler(client):
    response = client.get('/nonexistent-page-url-404')
    assert response.status_code == 404
