from __future__ import annotations

import functools
import os
import time
from typing import Any, Callable

from flask import Blueprint, Request, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from payroll.db import get_db, now_utc
from access import solely_owned_businesses

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

ROLES = {"admin", "viewer"}


def _audit(action: str, user: dict[str, Any] | None, description: str = "", entity_type: str = "", entity_id: int | None = None) -> None:
    # Deferred import: audit.routes imports this module, so a top-level
    # import here would create a circular dependency.
    from audit import service as audit_service
    audit_service.log(action, "auth", user, entity_type=entity_type, entity_id=entity_id, description=description)


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


def update_user_role(user_id: int, role: str) -> tuple[dict[str, Any], str]:
    """Update a user's role, returning the updated row and the previous role.

    The previous role is read inside the same immediate transaction as the
    update so callers auditing the change always see the transition that was
    actually committed, not a separate raceable read.
    """
    if role not in ROLES:
        raise ValueError("Invalid role")
    now = now_utc()
    with get_db() as conn:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("User not found")
        old_role = row["role"]
        conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role, now, user_id))
        updated = _row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        conn.execute("COMMIT")
        return updated, old_role


def delete_user(user_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("User not found")
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count <= 1:
            raise ValueError("Cannot delete the last user")
        if solely_owned_businesses(conn, user_id):
            raise ValueError(
                "User is the sole owner of a business; transfer ownership first"
            )
        conn.execute("DELETE FROM user_business_access WHERE user_id = ?", (user_id,))
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


def current_user() -> dict[str, Any] | None:
    """Resolve the session's user from persistent storage.

    The session only carries the user id; the role is always read fresh from
    the database so role changes, revocations and deletions take effect
    without requiring a new login.
    """
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_user_by_id(user_id)


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if current_user() is None:
            session.clear()
            return jsonify({"error": "Unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapped


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        user = current_user()
        if user is None:
            session.clear()
            return jsonify({"error": "Unauthorized"}), 401
        if user["role"] != "admin":
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

    # Public registration is only open while bootstrapping the very first
    # user, or when the deployment explicitly enables it. Authenticated
    # admins may always create users through this endpoint.
    user_count = _user_count()
    caller = current_user()
    caller_is_admin = caller is not None and caller["role"] == "admin"
    if user_count > 0 and not caller_is_admin and not _env_flag("ALLOW_REGISTRATION", False):
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
    if role != "viewer" and user_count > 0 and not caller_is_admin:
        return jsonify({"error": "Only admins can assign roles"}), 403

    if get_user_by_username(username) is not None:
        return jsonify({"error": "Username already exists"}), 409

    user = create_user(username, password, role)
    _audit("create", caller, f"Registered user '{username}' with role '{role}'", entity_type="user", entity_id=user["id"])
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]}), 201


_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 300


def _login_rate_limited(conn: Any, remote_addr: str, username: str, now: float) -> bool:
    # Expired rows are pruned on every attempt so the table stays bounded
    # instead of accumulating stale (ip, username) pairs in memory.
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (now - _LOGIN_WINDOW_SECONDS,))
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM login_attempts WHERE remote_addr = ? AND username = ?",
        (remote_addr, username),
    ).fetchone()
    return row["c"] >= _LOGIN_MAX_FAILURES


@bp.route("/login", methods=["POST"])
def login() -> Any:
    creds = _extract_credentials(request)
    if creds is None:
        return jsonify({"error": "Username and password are required"}), 400
    username, password = creds

    remote_addr = request.remote_addr or ""
    now = time.time()
    with get_db() as conn:
        # Attempts live in the shared database, so the limit applies across
        # processes/workers and not just within one in-memory map.
        if _login_rate_limited(conn, remote_addr, username, now):
            conn.commit()
            _audit("login_rate_limited", None, f"Rate-limited login for '{username}' from {remote_addr or 'unknown'}")
            return jsonify({"error": "Too many login attempts; try again later"}), 429

        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None or not check_password_hash(row["password_hash"], password):
            conn.execute(
                "INSERT INTO login_attempts (remote_addr, username, attempted_at) VALUES (?, ?, ?)",
                (remote_addr, username, now),
            )
            conn.commit()
            _audit("login_failed", None, f"Failed login for '{username}' from {remote_addr or 'unknown'}")
            return jsonify({"error": "Invalid credentials"}), 401
        conn.execute(
            "DELETE FROM login_attempts WHERE remote_addr = ? AND username = ?",
            (remote_addr, username),
        )
        conn.commit()
        user = _row_to_dict(row)
        _audit("login", user, f"Login from {remote_addr or 'unknown'}", entity_type="user", entity_id=user["id"])

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    return jsonify({"id": user["id"], "username": user["username"], "role": user["role"]})


@bp.route("/logout", methods=["POST"])
@login_required
def logout() -> Any:
    user = current_user()
    session.clear()
    _audit("logout", user, "Logged out", entity_type="user", entity_id=user["id"])
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
        updated, old_role = update_user_role(user_id, role)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    _audit("update", current_user(), f"Changed role for '{updated['username']}' from '{old_role}' to '{role}'", entity_type="user", entity_id=user_id)
    return jsonify(updated)


@bp.route("/users/<int:user_id>", methods=["DELETE"])
@admin_required
def remove_user(user_id: int) -> Any:
    # Capture the actor before the delete: if an admin removes their own
    # account, current_user() resolves to None afterwards.
    actor = current_user()
    target = get_user_by_id(user_id)
    try:
        delete_user(user_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    # Self-deletion must not leave a dangling user_id in audit_log: the row is
    # already gone, so record the username but null the reference.
    audit_user = {"id": None, "username": actor["username"]} if actor and actor["id"] == user_id else actor
    _audit("delete", audit_user, f"Deleted user '{target['username'] if target else user_id}'", entity_type="user", entity_id=user_id)
    return jsonify({"deleted": True})


def _ensure_default_admin(password: str | None) -> None:
    if not password:
        return
    if get_user_by_username("admin") is not None:
        return
    created = create_user("admin", password, "admin")
    _audit("create", None, "Bootstrapped default admin 'admin'", entity_type="user", entity_id=created["id"])


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

    # init_auth runs outside an app context; push one so the bootstrap lookup
    # and its audit entry use the configured database, not the default path.
    default_password = os.environ.get("DEFAULT_ADMIN_PASSWORD")
    with app.app_context():
        _ensure_default_admin(default_password)
