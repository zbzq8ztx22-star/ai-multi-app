from __future__ import annotations

import json
from typing import Any


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
