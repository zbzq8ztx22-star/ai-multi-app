from __future__ import annotations

from flask import Flask

from .db import DEFAULT_DB_PATH, init_db
from .routes import bp


def init_app(app: Flask) -> None:
    """Register the payroll blueprint and initialize the SQLite store."""
    app.config.setdefault("PAYROLL_DATABASE", str(DEFAULT_DB_PATH))
    app.register_blueprint(bp)
    with app.app_context():
        init_db()
