"""Test configuration.

IMPORTANT: Environment variables must be set before any app module is imported.
Settings() is instantiated at import time in app/config.py, so all os.environ
assignments must happen before any `from app` imports.
"""
import atexit
import os
import tempfile

# aiosqlite opens a new connection per call, and each :memory: connection gets
# its own fresh database — tables created in lifespan vanish for subsequent
# calls. Use a real temp file instead; PID-namespaced so parallel workers
# don't collide. Clean up automatically when the process exits.
_TEST_DB = os.path.join(tempfile.gettempdir(), f"test_gateway_{os.getpid()}.db")
atexit.register(lambda: os.unlink(_TEST_DB) if os.path.exists(_TEST_DB) else None)

os.environ.update({
    "GATEWAY_API_KEYS": "test-key",
    "DB_PATH": _TEST_DB,
    "GATEWAY_ENV": "development",
    "PIPELINE_PII_MODE": "off",           # skip Presidio calls in unit tests
    "PIPELINE_INJECTION_MODE": "block",
    "PIPELINE_STREAM_MODE": "buffered",
    "SIDECAR_FAIL_CLOSED": "false",
    "VERBOSE_ERRORS": "true",
    "RATE_LIMIT_RPM": "0",                # disable rate limiting in tests
    "RATE_LIMIT_TPM": "0",
    "LOG_LEVEL": "warning",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "GOOGLE_API_KEY": "",
})

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.state import stats as _stats


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset in-memory counters between tests so they don't bleed."""
    _stats.requests_total = 0
    _stats.requests_blocked = 0
    _stats.pii_detections = 0
    _stats.injection_detections = 0
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"x-api-key": "test-key"}
