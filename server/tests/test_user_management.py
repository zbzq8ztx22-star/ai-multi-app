def test_list_users_requires_admin(client):
    response = client.get("/api/auth/users")
    assert response.status_code == 200
    users = response.get_json()
    assert len(users) == 1
    assert users[0]["username"] == "testuser"
    assert users[0]["role"] == "admin"


def test_viewer_cannot_list_users(app):
    client = app.test_client()
    client.post("/api/auth/register", json={"username": "viewer1", "password": "pass1234", "role": "viewer"})
    client.post("/api/auth/login", json={"username": "viewer1", "password": "pass1234"})
    assert client.get("/api/auth/users").status_code == 403


def test_admin_can_change_role(client):
    client.post("/api/auth/register", json={"username": "user2", "password": "pass1234", "role": "viewer"})
    users = client.get("/api/auth/users").get_json()
    user2 = next(u for u in users if u["username"] == "user2")
    response = client.put(f"/api/auth/users/{user2['id']}/role", json={"role": "admin"})
    assert response.status_code == 200
    assert response.get_json()["role"] == "admin"


def test_change_role_invalid_role_rejected(client):
    users = client.get("/api/auth/users").get_json()
    user_id = users[0]["id"]
    response = client.put(f"/api/auth/users/{user_id}/role", json={"role": "superuser"})
    assert response.status_code == 400


def test_change_role_user_not_found(client):
    response = client.put("/api/auth/users/9999/role", json={"role": "admin"})
    assert response.status_code == 400


def test_admin_can_delete_user(client):
    client.post("/api/auth/register", json={"username": "user3", "password": "pass1234", "role": "viewer"})
    users = client.get("/api/auth/users").get_json()
    user3 = next(u for u in users if u["username"] == "user3")
    response = client.delete(f"/api/auth/users/{user3['id']}")
    assert response.status_code == 200
    users = client.get("/api/auth/users").get_json()
    assert all(u["username"] != "user3" for u in users)


def test_cannot_delete_last_user(client):
    users = client.get("/api/auth/users").get_json()
    response = client.delete(f"/api/auth/users/{users[0]['id']}")
    assert response.status_code == 400


def test_delete_user_not_found(client):
    response = client.delete("/api/auth/users/9999")
    assert response.status_code == 400


def test_user_management_endpoints_require_auth(app):
    client = app.test_client()
    assert client.get("/api/auth/users").status_code == 401
    assert client.put("/api/auth/users/1/role", json={"role": "admin"}).status_code == 401
    assert client.delete("/api/auth/users/1").status_code == 401
