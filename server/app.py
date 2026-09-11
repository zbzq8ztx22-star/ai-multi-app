from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, current_app, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent

# Make server/payroll importable whether the app is run from the project root
# or directly from the server directory.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from accounting import init_app as init_accounting
from audit import init_app as init_audit
from auth import init_auth, login_required
from backup import init_app as init_backup
from cost_centers import init_app as init_cost_centers
from currency import init_app as init_currency
from dashboard import init_app as init_dashboard
from entities import init_app as init_entities
from inventory import init_app as init_inventory
from payroll import init_app as init_payroll
from tax import init_app as init_tax

# Load .env from the server directory, but never let it override env vars that
# are already set (so tests can preset configuration).
_env_path = BASE_DIR / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)

DEFAULT_OPENEXECUTIVE_API_URL = "http://localhost:8000"

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".md", ".txt"}

logger = logging.getLogger(__name__)
http_session = requests.Session()
http_session.trust_env = False


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Application factory. Use this in tests; module-level ``app`` supports
    ``flask run`` / ``python app.py``."""
    app = Flask(__name__, static_folder=None)

    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024)
    )

    app.config["OPENEXECUTIVE_API_URL"] = os.environ.get(
        "OPENEXECUTIVE_API_URL", DEFAULT_OPENEXECUTIVE_API_URL
    ).rstrip("/")
    app.config["OPENEXECUTIVE_API_KEY"] = os.environ.get("OPENEXECUTIVE_API_KEY", "")
    app.config["OPENEXECUTIVE_TIMEOUT"] = int(os.environ.get("OPENEXECUTIVE_TIMEOUT", "120"))
    app.config["HEALTH_TIMEOUT"] = int(os.environ.get("HEALTH_TIMEOUT", "5"))
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "")

    if test_config:
        app.config.update(test_config)

    # CORS: CORS_ORIGINS env is comma-separated. Defaults to common local dev origins
    # so supports_credentials can be enabled safely. Set CORS_ORIGINS in production.
    origins_env = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    origins = [o.strip() for o in origins_env.split(",") if o.strip()] or ["http://localhost:3000"]
    supports_credentials = "*" not in origins
    CORS(
        app,
        origins=origins,
        supports_credentials=supports_credentials,
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # JSON error handlers so we never return Flask HTML pages or raw tracebacks.
    @app.errorhandler(400)
    def _bad_request(_exc: Any) -> tuple[Any, int]:
        return jsonify({"error": "Bad request"}), 400

    @app.errorhandler(404)
    def _not_found(_exc: Any) -> tuple[Any, int]:
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc: Any) -> tuple[Any, int]:
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(413)
    def _payload_too_large(_exc: Any) -> tuple[Any, int]:
        return jsonify({"error": "Payload too large"}), 413

    @app.errorhandler(415)
    def _unsupported_media(_exc: Any) -> tuple[Any, int]:
        return jsonify({"error": "Unsupported media type"}), 415

    @app.errorhandler(500)
    def _internal(_exc: Any) -> tuple[Any, int]:
        current_app.logger.exception("Internal server error")
        return jsonify({"error": "Internal server error"}), 500

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _openexec_headers() -> dict[str, str]:
        headers: dict[str, str] = {}
        key = current_app.config.get("OPENEXECUTIVE_API_KEY")
        if key:
            headers["x-api-key"] = key
        return headers

    def _openexec_url(path: str) -> str:
        return current_app.config["OPENEXECUTIVE_API_URL"] + path

    def parse_sse(text: str) -> dict[str, Any]:
        """Parse an SSE stream from OpenExecutive.

        Supports both the current ``type: chunk`` events and legacy
        ``type: content`` events. Preserves the first ``session_id`` seen and
        stops at the first ``error`` event. Returns a dict with ``text``,
        ``session_id``, ``error`` and ``events``.
        """
        chunks: list[str] = []
        legacy: list[str] = []
        session_id: str | None = None
        error: str | None = None
        events: list[dict[str, Any]] = []

        if not text:
            return {"text": "", "session_id": None, "error": None, "events": []}

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        for raw_event in text.split("\n\n"):
            lines = [ln for ln in raw_event.splitlines() if ln]
            if not lines:
                continue

            data_parts: list[str] = []
            for line in lines:
                if line.startswith("data:"):
                    data_parts.append(line[5:].lstrip())

            if not data_parts:
                continue

            payload = "\n".join(data_parts)
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if not isinstance(event, dict):
                continue

            events.append(event)

            event_session_id = event.get("session_id")
            if isinstance(event_session_id, str) and event_session_id:
                session_id = event_session_id

            event_type = event.get("type")
            if event_type == "chunk":
                chunks.append(str(event.get("content", "")))
            elif event_type == "content":
                # legacy
                legacy.append(str(event.get("content", "")))
            elif event_type == "error":
                error = str(event.get("message", "Upstream error"))
                session_id = event.get("session_id", session_id)
                break
            elif event_type == "done":
                session_id = event.get("session_id", session_id)
                break

        full_text = "".join(chunks) if chunks else "".join(legacy)
        return {
            "text": full_text,
            "session_id": session_id,
            "error": error,
            "events": events,
        }

    def _chat_with_openexec(
        message: str,
        session_id: str | None = None,
        committee_review: bool = False,
    ) -> requests.Response:
        """Forward a chat request to OpenExecutive and return the raw response."""
        payload: dict[str, Any] = {"message": message, "committee_review": bool(committee_review)}
        if session_id:
            payload["session_id"] = session_id

        return http_session.post(
            _openexec_url("/chat"),
            json=payload,
            headers=_openexec_headers(),
            timeout=current_app.config["OPENEXECUTIVE_TIMEOUT"],
        )

    def _handle_chat_response(
        resp: requests.Response, original_session_id: str | None = None
    ) -> tuple[Any, int]:
        """Consume an OpenExecutive SSE chat response and return a JSON Flask response."""
        if resp.status_code >= 500:
            current_app.logger.error("OpenExecutive returned %s", resp.status_code)
            return jsonify({"error": "OpenExecutive error"}), 502
        if resp.status_code >= 400:
            return jsonify({"error": "OpenExecutive rejected the request"}), 502

        parsed = parse_sse(resp.text)
        if parsed["error"]:
            return jsonify({
                "error": parsed["error"],
                "session_id": parsed["session_id"] or original_session_id,
            }), 502

        if not parsed["text"]:
            return jsonify({"error": "OpenExecutive returned an empty response"}), 502

        session_id = parsed["session_id"] or original_session_id
        return jsonify({"response": parsed["text"], "session_id": session_id}), 200

    def _strip_code_fences(text: str) -> str:
        """Remove leading/trailing markdown code fences if present."""
        text = text.strip()
        # Remove an opening ``` or ```python etc. and a closing ```.
        text = re.sub(r"^```(?:\w+)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        return text.strip()

    # ------------------------------------------------------------------ #
    # Routes
    # ------------------------------------------------------------------ #

    @app.route("/")
    def index() -> Any:
        dist_dir = BASE_DIR.parent / "dist"
        if not (dist_dir / "index.html").is_file():
            return jsonify({"error": "Frontend build not found. Run npm run build."}), 503
        return send_from_directory(dist_dir, "index.html")

    @app.route("/assets/<path:filename>")
    def frontend_asset(filename: str) -> Any:
        return send_from_directory(BASE_DIR.parent / "dist" / "assets", filename)

    @app.route("/api/chat", methods=["POST"])
    @login_required
    def chat() -> Any:
        if not request.is_json:
            return jsonify({"error": "Request body must be JSON"}), 400

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON body"}), 400

        message_value = data.get("message")
        if not isinstance(message_value, str) or not message_value.strip():
            return jsonify({"error": "message must be a non-empty string"}), 400
        message = message_value.strip()

        session_id = data.get("session_id")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            return jsonify({"error": "session_id must be a non-empty string"}), 400

        committee_review = data.get("committee_review", False)
        if not isinstance(committee_review, bool):
            return jsonify({"error": "committee_review must be a boolean"}), 400

        try:
            resp = _chat_with_openexec(message, session_id, committee_review)
            return _handle_chat_response(resp, session_id)
        except requests.exceptions.ConnectionError:
            current_app.logger.warning("OpenExecutive connection refused at %s", _openexec_url("/chat"))
            return jsonify({"error": "OpenExecutive service unavailable"}), 503
        except requests.exceptions.Timeout:
            return jsonify({"error": "OpenExecutive request timed out"}), 503
        except requests.exceptions.RequestException:
            return jsonify({"error": "OpenExecutive request failed"}), 502
        except Exception:
            current_app.logger.exception("Unhandled error in /api/chat")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/vision", methods=["POST"])
    @login_required
    def vision() -> Any:
        if "image" not in request.files:
            return jsonify({"error": "image file is required"}), 400

        file = request.files["image"]
        if not file or file.filename == "":
            return jsonify({"error": "image filename is required"}), 400

        filename = secure_filename(file.filename)
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return jsonify({"error": f"Unsupported image type: {ext}"}), 415

        content = file.read()
        if len(content) > current_app.config["MAX_CONTENT_LENGTH"]:
            return jsonify({"error": "Image too large"}), 413

        message = (request.form.get("message") or "").strip()
        message = message or "Describe the contents of this image."
        session_id = (request.form.get("session_id") or "").strip() or None

        data: dict[str, Any] = {"message": message}
        if session_id:
            data["session_id"] = session_id
        if "committee_review" in request.form:
            data["committee_review"] = request.form.get("committee_review", "").lower() in (
                "true", "1", "yes"
            )

        content_type = file.content_type or "application/octet-stream"
        files = [("files", (filename, io.BytesIO(content), content_type))]

        try:
            resp = http_session.post(
                _openexec_url("/chat/upload"),
                data=data,
                files=files,
                headers=_openexec_headers(),
                timeout=current_app.config["OPENEXECUTIVE_TIMEOUT"],
            )
            result, status = _handle_chat_response(resp, session_id)
            if status != 200:
                return result, status
            body = result.get_json(force=True) or {}
            return jsonify({
                "analysis": body.get("response", ""),
                "session_id": body.get("session_id"),
            }), 200
        except requests.exceptions.ConnectionError:
            current_app.logger.warning("OpenExecutive connection refused at %s", _openexec_url("/chat/upload"))
            return jsonify({"error": "OpenExecutive service unavailable"}), 503
        except requests.exceptions.Timeout:
            return jsonify({"error": "OpenExecutive request timed out"}), 503
        except requests.exceptions.RequestException:
            return jsonify({"error": "OpenExecutive request failed"}), 502
        except Exception:
            current_app.logger.exception("Unhandled error in /api/vision")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/code", methods=["POST"])
    @login_required
    def code() -> Any:
        if not request.is_json:
            return jsonify({"error": "Request body must be JSON"}), 400

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON body"}), 400

        prompt_value = data.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            return jsonify({"error": "prompt must be a non-empty string"}), 400
        prompt = prompt_value.strip()

        language = str(data.get("language") or "python").strip().lower() or "python"
        session_id = data.get("session_id")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            return jsonify({"error": "session_id must be a non-empty string"}), 400

        message = (
            f"Generate only executable {language} code for the following request. "
            f"Do not include explanations, markdown code fences, or prose. "
            f"Output only the code itself.\n\nRequest: {prompt}"
        )

        try:
            resp = _chat_with_openexec(message, session_id, committee_review=False)
            result, status = _handle_chat_response(resp, session_id)
            if status != 200:
                return result, status

            body = result.get_json(force=True) or {}
            code_text = _strip_code_fences(body.get("response", ""))
            return jsonify({"code": code_text, "session_id": body.get("session_id")}), 200
        except requests.exceptions.ConnectionError:
            return jsonify({"error": "OpenExecutive service unavailable"}), 503
        except requests.exceptions.Timeout:
            return jsonify({"error": "OpenExecutive request timed out"}), 503
        except requests.exceptions.RequestException:
            return jsonify({"error": "OpenExecutive request failed"}), 502
        except Exception:
            current_app.logger.exception("Unhandled error in /api/code")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/docs", methods=["POST"])
    @login_required
    def docs() -> Any:
        if "document" not in request.files:
            return jsonify({"error": "document file is required"}), 400

        file = request.files["document"]
        if not file or file.filename == "":
            return jsonify({"error": "document filename is required"}), 400

        filename = secure_filename(file.filename)
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            return jsonify({
                "error": (
                    f"Unsupported document type: {ext}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))}"
                )
            }), 415

        content = file.read()
        if len(content) > current_app.config["MAX_CONTENT_LENGTH"]:
            return jsonify({"error": "Document too large"}), 413

        domain = (request.form.get("domain") or "").strip() or "general"
        if not re.match(r"^[A-Za-z0-9_-]+$", domain):
            return jsonify({"error": "Invalid domain"}), 400

        content_type = file.content_type or "application/octet-stream"
        files = {"file": (filename, io.BytesIO(content), content_type)}
        data = {"domain": domain}

        try:
            resp = http_session.post(
                _openexec_url("/documents"),
                files=files,
                data=data,
                headers=_openexec_headers(),
                timeout=current_app.config["OPENEXECUTIVE_TIMEOUT"],
            )
            if resp.status_code == 200:
                try:
                    upstream = resp.json()
                except ValueError:
                    return jsonify({"error": "Invalid response from OpenExecutive"}), 502
                if not isinstance(upstream, dict):
                    return jsonify({"error": "Invalid response from OpenExecutive"}), 502

                chunks_indexed = upstream.get("chunks_indexed", 0)
                summary = (
                    f"Indexed {chunks_indexed} chunk(s) from "
                    f"{upstream.get('filename', filename)} under "
                    f"{upstream.get('domain', domain)} "
                    f"(status: {upstream.get('status', 'indexed')})."
                )
                result = {
                    "filename": upstream.get("filename", filename),
                    "chunks_indexed": chunks_indexed,
                    "domain": upstream.get("domain", domain),
                    "status": upstream.get("status", "indexed"),
                    "summary": summary,
                    "analysis": summary,
                }
                return jsonify(result), 200
            elif resp.status_code >= 500:
                current_app.logger.error("OpenExecutive /documents returned %s", resp.status_code)
                return jsonify({"error": "OpenExecutive error"}), 502
            else:
                return jsonify({"error": "OpenExecutive rejected the document"}), 502
        except requests.exceptions.ConnectionError:
            current_app.logger.warning("OpenExecutive connection refused at %s", _openexec_url("/documents"))
            return jsonify({"error": "OpenExecutive service unavailable"}), 503
        except requests.exceptions.Timeout:
            return jsonify({"error": "OpenExecutive request timed out"}), 503
        except requests.exceptions.RequestException:
            return jsonify({"error": "OpenExecutive request failed"}), 502
        except Exception:
            current_app.logger.exception("Unhandled error in /api/docs")
            return jsonify({"error": "Internal server error"}), 500

    @app.route("/api/health", methods=["GET"])
    def health() -> Any:
        try:
            resp = http_session.get(
                _openexec_url("/health"),
                headers=_openexec_headers(),
                timeout=current_app.config["HEALTH_TIMEOUT"],
            )
            if resp.status_code == 200:
                try:
                    upstream = resp.json()
                except ValueError:
                    upstream = {"raw": resp.text}
                status = upstream.get("status") if isinstance(upstream, dict) else None
                return jsonify({"status": status or "ok", "openexecutive": "connected"}), 200

            current_app.logger.warning("OpenExecutive /health returned %s", resp.status_code)
            return jsonify({"error": "OpenExecutive health check failed"}), 502
        except requests.exceptions.ConnectionError:
            return jsonify({"error": "OpenExecutive service unavailable"}), 503
        except requests.exceptions.Timeout:
            return jsonify({"error": "OpenExecutive health check timed out"}), 503
        except requests.exceptions.RequestException:
            return jsonify({"error": "OpenExecutive request failed"}), 502
        except Exception:
            current_app.logger.exception("Unhandled error in /api/health")
            return jsonify({"error": "Internal server error"}), 500

    init_payroll(app)
    init_auth(app)
    init_entities(app)
    init_tax(app)
    init_accounting(app)
    init_dashboard(app)
    init_audit(app)
    init_backup(app)
    init_currency(app)
    init_cost_centers(app)
    init_inventory(app)
    return app


# Module-level app for ``flask run`` / direct execution.
app = create_app()

if __name__ == "__main__":
    # Debug is disabled unless explicitly enabled via FLASK_DEBUG.
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug)
