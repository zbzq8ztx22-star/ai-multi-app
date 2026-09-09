import os

import pytest

from app import create_app

# Set test-safe config before app.py is imported so create_app() picks it up.
os.environ["OPENEXECUTIVE_API_URL"] = "http://openexec.test"
os.environ["OPENEXECUTIVE_API_KEY"] = "test-key"
os.environ["FLASK_DEBUG"] = "0"
os.environ["CORS_ORIGINS"] = "*"


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "payroll.db"
    return create_app(test_config={"PAYROLL_DATABASE": str(db_path)})


@pytest.fixture
def client(app):
    return app.test_client()
