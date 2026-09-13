from __future__ import annotations

import functools
import os
from typing import Any, Callable

from flask import Blueprint, Request, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from payroll.db import get_db, now_utc

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

ROLES = {"admin", "viewer"}


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _row_to_dict(row) if row else None


def _user_count() -> int:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return row["c"]


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT id, username, role, created_at, updated_at FROM users ORDER BY id").fetchall()
        return [_row_to_dict(row) for row in rows]


def update_user_role(user_id: int, role: str) -> dict[str, Any]:
    if role not in ROLES:
        raise ValueError("Invalid role")
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("User not found")
        conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role, now, user_id))
        conn.commit()
        return _row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def delete_user(user_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("User not found")
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count <= 1:
            raise ValueError("Cannot delete the last user")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


def create_user(username: str, password: str, role: str = "viewer") -> dict[str, Any]:
    if role not in ROLES:
        raise ValueError("Invalid role")
    hashed = generate_password_hash(password)
    now = now_utc()
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, hashed, role, now, now),
        )
        conn.commit()
        return get_user_by_id(cursor.lastrowid)


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if "user_id" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapped


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if "user_id" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "Forbidden"}), 403
        return view(*args, **kwargs)

    return wrapped


def _extract_credentials(req: Request) -> tuple[str, str] | None:
    data = req.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        return None
    return username, password


@bp.route("/register", methods=["POST"])
def register() -> Any:
    if os.environ.get("DISABLE_REGISTRATION"):
        return jsonify({"error": "Registration is disabled"}), 403

    creds = _extract_credentials(request)
    if creds is None:
        return jsonify({"error": "Username and password are required"}), 400
    username, password = creds

    data = request.get_json(silent=True) or {}
    role = data.get("role", "viewer")
    if role not in ROLES:
        return jsonify({"error": "Invalid role"}), 400

    # Elevated roles may only be assigned when bootstrapping the very first
    # user or by a logged-in admin; anyone can register as a viewer.
    if role != "viewer" and _user_count() > 0 and session.get("role") != "admin":
        return jsonify({"error": "Only admins can assign roles"}), 403

    if get_user_by_username(username) is not None:
        return jsonify({"error": "Username already exists"}), 409

    user = create_user(username, password, role)
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]}), 201


@bp.route("/login", methods=["POST"])
def login() -> Any:
    creds = _extract_credentials(request)
    if creds is None:
        return jsonify({"error": "Username and password are required"}), 400
    username, password = creds

    user = get_user_by_username(username)
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid credentials"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]})


@bp.route("/logout", methods=["POST"])
@login_required
def logout() -> Any:
    session.clear()
    return jsonify({"status": "ok"})


@bp.route("/me", methods=["GET"])
def me() -> Any:
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = get_user_by_id(session["user_id"])
    if user is None:
        session.clear()
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]})


@bp.route("/users", methods=["GET"])
@admin_required
def users() -> Any:
    return jsonify(list_users())


@bp.route("/users/<int:user_id>/role", methods=["PUT"])
@admin_required
def change_role(user_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    role = str(data.get("role", "")).strip()
    try:
        return jsonify(update_user_role(user_id, role))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/users/<int:user_id>", methods=["DELETE"])
@admin_required
def remove_user(user_id: int) -> Any:
    try:
        delete_user(user_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def _ensure_default_admin(password: str | None) -> None:
    if not password:
        return
    if get_user_by_username("admin") is not None:
        return
    create_user("admin", password, "admin")


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no")


def init_auth(app: Any) -> None:
    """Configure session secret key and register auth routes."""
    secret_key = app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
    if not secret_key:
        raise ValueError(
            "SECRET_KEY is required. Set the SECRET_KEY environment variable "
            "or add it to your Flask app config."
        )
    app.secret_key = secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    app.config["SESSION_COOKIE_SECURE"] = _env_flag("SESSION_COOKIE_SECURE", True)
    app.register_blueprint(bp)

    default_password = os.environ.get("DEFAULT_ADMIN_PASSWORD")
    _ensure_default_admin(default_password)
