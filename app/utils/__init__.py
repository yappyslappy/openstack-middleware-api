from __future__ import annotations

from typing import Any

from flask import jsonify
from flask.typing import ResponseReturnValue


def success_response(data: Any, status_code: int = 200) -> ResponseReturnValue:
    """Build a standardized successful JSON response."""
    return jsonify({"status": "success", "data": data}), status_code
