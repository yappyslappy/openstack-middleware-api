from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import jsonify
from flask.typing import ResponseReturnValue


def success_response(
    data: Any,
    status_code: int = 200,
    meta: Mapping[str, Any] | None = None,
) -> ResponseReturnValue:
    """Build a standardized successful JSON response."""
    payload = {"status": "success", "data": data}
    if meta is not None:
        payload["meta"] = dict(meta)
    return jsonify(payload), status_code
