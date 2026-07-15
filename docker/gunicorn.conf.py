from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if parsed < 1:
        raise RuntimeError(f"{name} must be at least 1.")
    return parsed


bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
workers = _int_env("GUNICORN_WORKERS", 4)
threads = _int_env("GUNICORN_THREADS", 2)
timeout = _int_env("GUNICORN_TIMEOUT", 60)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int_env("GUNICORN_KEEPALIVE", 5)
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 5000)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 500)

loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"

forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")
proxy_allow_ips = forwarded_allow_ips
secure_scheme_headers = {"X-FORWARDED-PROTO": "https"}
