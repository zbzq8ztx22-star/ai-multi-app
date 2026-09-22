import os

import pytest

# Set test-safe config before app.py is imported so create_app() picks it up.
os.environ["OPENEXECUTIVE_API_URL"] = "http://openexec.test"
os.environ["OPENEXECUTIVE_API_KEY"] = "test-key"
os.environ["FLASK_DEBUG"] = "0"
os.environ["CORS_ORIGINS"] = "*"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["SESSION_COOKIE_SECURE"] = "0"
os.environ["ALLOW_REGISTRATION"] = "1"

from app import create_app


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "payroll.db"
    return create_app(test_config={"PAYROLL_DATABASE": str(db_path)})


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        test_client.post(
            "/api/auth/register",
            json={"username": "testuser", "password": "testpassword", "role": "admin"},
        )
        test_client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "testpassword"},
        )
        yield test_client
