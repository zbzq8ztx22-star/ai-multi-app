from __future__ import annotations

import json
from typing import Any

import requests
from flask import current_app

# Isolated session for OpenExecutive requests. ``trust_env=False`` prevents
# the process from routing traffic through system proxies or leaking
# credentials via .netrc.
http_session = requests.Session()
http_session.trust_env = False


def _openexec_url(path: str) -> str:
    return current_app.config["OPENEXECUTIVE_API_URL"].rstrip("/") + path


def _openexec_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    key = current_app.config.get("OPENEXECUTIVE_API_KEY")
    if key:
        headers["x-api-key"] = key
    return headers


def parse_sse(text: str) -> dict[str, Any]:
    """Parse an SSE stream from OpenExecutive.

    Supports ``chunk`` and legacy ``content`` events, captures ``session_id``,
    and stops at the first ``error`` or ``done`` event.
    """
    chunks: list[str] = []
    legacy: list[str] = []
    session_id: str | None = None
    error: str | None = None

    if not text:
        return {"text": "", "session_id": None, "error": None}

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

        event_session_id = event.get("session_id")
        if isinstance(event_session_id, str) and event_session_id:
            session_id = event_session_id

        event_type = event.get("type")
        if event_type == "chunk":
            chunks.append(str(event.get("content", "")))
        elif event_type == "content":
            legacy.append(str(event.get("content", "")))
        elif event_type == "error":
            error = str(event.get("message", "Upstream error"))
            session_id = event.get("session_id", session_id)
            break
        elif event_type == "done":
            session_id = event.get("session_id", session_id)
            break

    full_text = "".join(chunks) if chunks else "".join(legacy)
    return {"text": full_text, "session_id": session_id, "error": error}


def chat(
    message: str,
    session_id: str | None = None,
    committee_review: bool = False,
) -> dict[str, Any]:
    """Send a chat message to OpenExecutive and return the parsed response."""
    payload: dict[str, Any] = {
        "message": message,
        "committee_review": bool(committee_review),
    }
    if session_id:
        payload["session_id"] = session_id

    try:
        resp = http_session.post(
            _openexec_url("/chat"),
            json=payload,
            headers=_openexec_headers(),
            timeout=current_app.config["OPENEXECUTIVE_TIMEOUT"],
        )
    except requests.exceptions.RequestException as exc:
        return {"error": f"OpenExecutive request failed: {exc}", "session_id": session_id}

    if resp.status_code >= 500:
        return {"error": "OpenExecutive error", "session_id": session_id}
    if resp.status_code >= 400:
        return {"error": "OpenExecutive rejected the request", "session_id": session_id}

    parsed = parse_sse(resp.text)
    if parsed["error"]:
        return {"error": parsed["error"], "session_id": parsed["session_id"] or session_id}

    if not parsed["text"]:
        return {"error": "OpenExecutive returned an empty response", "session_id": parsed["session_id"] or session_id}

    return {
        "response": parsed["text"],
        "session_id": parsed["session_id"] or session_id,
    }
