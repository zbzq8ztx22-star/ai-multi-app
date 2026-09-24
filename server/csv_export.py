"""Shared CSV export helpers.

``sanitize_csv_field`` neutralizes spreadsheet-formula injection: any text
cell that begins with a formula prefix is prefixed with a single quote so
Excel/LibreOffice render it as inert text instead of evaluating it.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from flask import Response

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def sanitize_csv_field(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip()[:1] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def csv_response(rows: list[list[Any]], filename: str) -> Response:
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow([sanitize_csv_field(value) for value in row])
    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
