from __future__ import annotations

import io
import json
from typing import Any

import pytest
import requests


class MockResponse:
    """A minimal stand-in for ``requests.Response``."""

    def __init__(
        self,
        text: str = "",
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        if self._json is None:
            raise ValueError("No JSON body")
        return self._json


def _sse_event(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event) + "\n\n"


# --------------------------------------------------------------------------- #
# /api/chat
# --------------------------------------------------------------------------- #


def test_api_chat_sse_chunks_and_session(client, monkeypatch):
    sse = (
        _sse_event({"type": "chunk", "content": "Hello ", "session_id": "sess-123"})
        + _sse_event({"type": "chunk", "content": "world", "session_id": "sess-123"})
        + _sse_event({"type": "done", "session_id": "sess-123"})
    )
    calls: dict[str, Any] = {}

    def mock_post(url, **kwargs):
        calls["url"] = url
        calls["json"] = kwargs.get("json")
        calls["headers"] = kwargs.get("headers")
        return MockResponse(text=sse, status_code=200)

    monkeypatch.setattr("app.http_session.post", mock_post)

    resp = client.post(
        "/api/chat",
        json={"message": "hi", "session_id": "sess-existing", "committee_review": True},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "Hello world"
    assert body["session_id"] == "sess-123"
    assert calls["url"] == "http://openexec.test/chat"
    assert calls["json"]["message"] == "hi"
    assert calls["json"]["session_id"] == "sess-existing"
    assert calls["json"]["committee_review"] is True
    assert calls["headers"]["x-api-key"] == "test-key"


def test_api_chat_does_not_allow_client_to_override_api_key(client, monkeypatch):
    calls: dict[str, Any] = {}

    def mock_post(url, **kwargs):
        calls["headers"] = kwargs.get("headers")
        return MockResponse(
            text=_sse_event({"type": "chunk", "content": "ok", "session_id": "s"}),
            status_code=200,
        )

    monkeypatch.setattr("app.http_session.post", mock_post)

    resp = client.post(
        "/api/chat",
        json={"message": "hi"},
        headers={"X-Api-Key": "client-key"},
    )

    assert resp.status_code == 200
    assert calls["headers"]["x-api-key"] == "test-key"


def test_api_chat_legacy_content_events(client, monkeypatch):
    sse = (
        _sse_event({"type": "content", "content": "Legacy ", "session_id": "sess-leg"})
        + _sse_event({"type": "content", "content": "response", "session_id": "sess-leg"})
        + _sse_event({"type": "done", "session_id": "sess-leg"})
    )
    monkeypatch.setattr("app.http_session.post", lambda *a, **k: MockResponse(text=sse, status_code=200))

    resp = client.post("/api/chat", json={"message": "hi"})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["response"] == "Legacy response"
    assert body["session_id"] == "sess-leg"


def test_api_chat_empty_sse_returns_502(client, monkeypatch):
    monkeypatch.setattr(
        "app.http_session.post",
        lambda *a, **k: MockResponse(
            text=_sse_event({"type": "done", "session_id": "sess-empty"}),
            status_code=200,
        ),
    )

    resp = client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 502
    assert "empty response" in resp.get_json()["error"].lower()


def test_api_chat_sse_error_returns_502(client, monkeypatch):
    sse = _sse_event({"type": "error", "message": "model failure", "session_id": "sess-err"})
    monkeypatch.setattr("app.http_session.post", lambda *a, **k: MockResponse(text=sse, status_code=200))

    resp = client.post("/api/chat", json={"message": "hi"})
    body = resp.get_json()

    assert resp.status_code == 502
    assert "model failure" in body["error"]
    assert body["session_id"] == "sess-err"


def test_api_chat_validation_missing_message(client):
    resp = client.post("/api/chat", json={})
    assert resp.status_code == 400
    assert "message" in resp.get_json()["error"].lower()


def test_api_chat_validation_empty_message(client):
    resp = client.post("/api/chat", json={"message": "   "})
    assert resp.status_code == 400


def test_api_chat_validation_non_json(client):
    resp = client.post("/api/chat", data="not json", content_type="application/json")
    assert resp.status_code == 400


@pytest.mark.parametrize("payload", [{"message": None}, {"message": 42}])
def test_api_chat_rejects_non_string_message(client, payload):
    resp = client.post("/api/chat", json=payload)
    assert resp.status_code == 400


def test_api_chat_rejects_non_boolean_committee_review(client):
    resp = client.post("/api/chat", json={"message": "hi", "committee_review": "false"})
    assert resp.status_code == 400


def test_api_chat_parses_crlf_multiline_sse_and_late_session(client, monkeypatch):
    sse = (
        'data: {\r\n'
        'data: "type": "chunk", "content": "Hello"\r\n'
        'data: }\r\n\r\n'
        + _sse_event({"type": "done", "session_id": "late-session"}).replace("\n", "\r\n")
    )
    monkeypatch.setattr("app.http_session.post", lambda *a, **k: MockResponse(text=sse, status_code=200))

    resp = client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 200
    assert resp.get_json() == {"response": "Hello", "session_id": "late-session"}


def test_api_chat_connection_error_returns_503(client, monkeypatch):
    def mock_post(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr("app.http_session.post", mock_post)

    resp = client.post("/api/chat", json={"message": "hi"})
    body = resp.get_json()

    assert resp.status_code == 503
    assert "unavailable" in body["error"].lower()


def test_api_chat_upstream_500_returns_502(client, monkeypatch):
    monkeypatch.setattr(
        "app.http_session.post",
        lambda *a, **k: MockResponse(text="Internal Server Error", status_code=500),
    )

    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 502
    assert "openexecutive error" in resp.get_json()["error"].lower()


def test_api_chat_no_exception_leak(client, monkeypatch):
    def mock_post(*a, **k):
        raise RuntimeError("secret traceback")

    monkeypatch.setattr("app.http_session.post", mock_post)

    resp = client.post("/api/chat", json={"message": "hi"})
    body = resp.get_json()

    assert resp.status_code == 500
    assert "secret traceback" not in str(body)
    assert "internal server error" in body["error"].lower()


# --------------------------------------------------------------------------- #
# /api/vision
# --------------------------------------------------------------------------- #


def test_api_vision_forwards_image_to_chat_upload(client, monkeypatch):
    calls: dict[str, Any] = {}

    def mock_post(url, **kwargs):
        calls["url"] = url
        calls["data"] = kwargs.get("data")
        calls["files"] = kwargs.get("files")
        calls["headers"] = kwargs.get("headers")
        sse = _sse_event({"type": "chunk", "content": "An image.", "session_id": "sess-vis"})
        return MockResponse(text=sse, status_code=200)

    monkeypatch.setattr("app.http_session.post", mock_post)

    resp = client.post(
        "/api/vision",
        data={
            "image": (io.BytesIO(b"fake image data"), "test.png"),
            "message": "What is in this image?",
            "session_id": "sess-1",
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["analysis"] == "An image."
    assert body["session_id"] == "sess-vis"
    assert calls["url"] == "http://openexec.test/chat/upload"
    assert calls["data"]["message"] == "What is in this image?"
    assert calls["data"]["session_id"] == "sess-1"
    assert calls["headers"]["x-api-key"] == "test-key"

    # files list: [(field_name, (filename, stream, content_type))]
    assert len(calls["files"]) == 1
    field_name, file_tuple = calls["files"][0]
    assert field_name == "files"
    filename, stream, content_type = file_tuple
    assert filename == "test.png"
    stream.seek(0)
    assert stream.read() == b"fake image data"
    assert content_type == "image/png"


def test_api_vision_missing_image(client):
    resp = client.post("/api/vision", data={})
    assert resp.status_code == 400


def test_api_vision_invalid_image_type(client):
    resp = client.post(
        "/api/vision",
        data={"image": (io.BytesIO(b"fake"), "malware.exe")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 415


# --------------------------------------------------------------------------- #
# /api/code
# --------------------------------------------------------------------------- #


def test_api_code_constrained_prompt(client, monkeypatch):
    calls: dict[str, Any] = {}

    def mock_post(url, **kwargs):
        calls["url"] = url
        calls["json"] = kwargs.get("json")
        sse = _sse_event({
            "type": "chunk",
            "content": "def sort_list(items):\n    return sorted(items)",
            "session_id": "sess-code",
        })
        return MockResponse(text=sse, status_code=200)

    monkeypatch.setattr("app.http_session.post", mock_post)

    resp = client.post(
        "/api/code",
        json={"prompt": "sort a list", "language": "python", "session_id": "sess-code"},
    )

    body = resp.get_json()
    assert resp.status_code == 200
    assert "def sort_list" in body["code"]
    assert body["session_id"] == "sess-code"
    assert calls["url"] == "http://openexec.test/chat"
    assert calls["json"]["message"].startswith("Generate only executable python code")
    assert "sort a list" in calls["json"]["message"]
    assert calls["json"]["committee_review"] is False


def test_api_code_strips_markdown_fences(client, monkeypatch):
    sse = _sse_event({
        "type": "chunk",
        "content": "```python\ndef add(a, b):\n    return a + b\n```",
        "session_id": "sess-fence",
    })
    monkeypatch.setattr("app.http_session.post", lambda *a, **k: MockResponse(text=sse, status_code=200))

    resp = client.post("/api/code", json={"prompt": "add function", "language": "python"})
    code = resp.get_json()["code"]

    assert "```" not in code
    assert code.startswith("def add")


def test_api_code_validation_missing_prompt(client):
    resp = client.post("/api/code", json={"language": "python"})
    assert resp.status_code == 400


@pytest.mark.parametrize("prompt", [None, 42])
def test_api_code_rejects_non_string_prompt(client, prompt):
    resp = client.post("/api/code", json={"prompt": prompt, "language": "python"})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# /api/docs
# --------------------------------------------------------------------------- #


def test_api_docs_forwards_upload_and_returns_summary(client, monkeypatch):
    calls: dict[str, Any] = {}

    def mock_post(url, **kwargs):
        calls["url"] = url
        calls["data"] = kwargs.get("data")
        calls["files"] = kwargs.get("files")
        calls["headers"] = kwargs.get("headers")
        return MockResponse(
            json_data={
                "filename": "plan.md",
                "chunks_indexed": 3,
                "domain": "finance",
                "status": "indexed",
            },
            status_code=200,
        )

    monkeypatch.setattr("app.http_session.post", mock_post)

    resp = client.post(
        "/api/docs",
        data={
            "document": (io.BytesIO(b"# Plan\nGrow revenue 30%."), "plan.md"),
            "domain": "finance",
        },
        content_type="multipart/form-data",
    )

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["filename"] == "plan.md"
    assert body["chunks_indexed"] == 3
    assert body["domain"] == "finance"
    assert body["status"] == "indexed"
    assert "Indexed 3 chunk(s)" in body["summary"]
    assert body["analysis"] == body["summary"]
    assert calls["url"] == "http://openexec.test/documents"
    assert calls["data"]["domain"] == "finance"
    assert calls["headers"]["x-api-key"] == "test-key"
    # Ensure the uploaded file was not saved to disk by checking the stream matches.
    file_tuple = calls["files"]["file"]
    filename, stream, _content_type = file_tuple
    assert filename == "plan.md"
    stream.seek(0)
    assert stream.read() == b"# Plan\nGrow revenue 30%."


def test_api_docs_missing_document(client):
    resp = client.post("/api/docs", data={"domain": "finance"})
    assert resp.status_code == 400


def test_api_docs_invalid_extension(client):
    resp = client.post(
        "/api/docs",
        data={"document": (io.BytesIO(b"bad"), "file.exe")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 415


def test_api_docs_too_large(client, monkeypatch):
    monkeypatch.setitem(client.application.config, "MAX_CONTENT_LENGTH", 10)
    resp = client.post(
        "/api/docs",
        data={"document": (io.BytesIO(b"a" * 20), "big.txt"), "domain": "general"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413


# --------------------------------------------------------------------------- #
# /api/health
# --------------------------------------------------------------------------- #


def test_api_health_connected(client, monkeypatch):
    def mock_get(url, **kwargs):
        return MockResponse(
            json_data={
                "status": "ok",
                "builtin_knowledge_chunks": 10,
                "company_profile_loaded": True,
            },
            status_code=200,
        )

    monkeypatch.setattr("app.http_session.get", mock_get)

    resp = client.get("/api/health")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body == {"status": "ok", "openexecutive": "connected"}


def test_api_health_unavailable(client, monkeypatch):
    def mock_get(url, **kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr("app.http_session.get", mock_get)

    resp = client.get("/api/health")
    body = resp.get_json()

    assert resp.status_code == 503
    assert "unavailable" in body["error"].lower()


def test_api_health_upstream_error(client, monkeypatch):
    monkeypatch.setattr(
        "app.http_session.get",
        lambda *a, **k: MockResponse(text="Bad Gateway", status_code=502),
    )

    resp = client.get("/api/health")
    body = resp.get_json()

    assert resp.status_code == 502
    assert "health check failed" in body["error"].lower()
