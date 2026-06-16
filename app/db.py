"""SQLite persistence — audit logs and rate limit counters."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

_CREATE_AUDIT = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    TEXT    NOT NULL,
    timestamp     TEXT    NOT NULL,
    api_key_hash  TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    provider      TEXT    NOT NULL,
    blocked       INTEGER NOT NULL DEFAULT 0,
    risk_score    INTEGER NOT NULL DEFAULT 0,
    severity      TEXT    NOT NULL DEFAULT 'low',
    reasons       TEXT    NOT NULL DEFAULT '[]',
    latency_ms    REAL    NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL    NOT NULL DEFAULT 0.0
)
"""

_CREATE_RATE_LIMIT = """
CREATE TABLE IF NOT EXISTS rate_limit_counters (
    api_key_hash   TEXT    NOT NULL,
    window_minute  TEXT    NOT NULL,
    request_count  INTEGER NOT NULL DEFAULT 0,
    token_count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (api_key_hash, window_minute)
)
"""

# Token cost per 1 000 tokens (input, output) in USD
_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o":                    (0.0025,  0.010),
    "gpt-4o-mini":               (0.00015, 0.0006),
    "gpt-4-turbo":               (0.010,   0.030),
    "claude-opus-4-7":           (0.015,   0.075),
    "claude-sonnet-4-6":         (0.003,   0.015),
    "claude-haiku-4-5-20251001": (0.00025, 0.00125),
    "gemini-1.5-pro":            (0.00125, 0.005),
    "gemini-1.5-flash":          (0.000075,0.0003),
    "gemini-2.0-flash-exp":      (0.000075,0.0003),
}


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = _TOKEN_PRICES.get(model)
    if not prices:
        return 0.0
    ip, op = prices
    return (input_tokens / 1000 * ip) + (output_tokens / 1000 * op)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minute_window() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")


_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL
)
"""

# Ordered migration list — APPEND ONLY, never edit or remove existing entries.
# Version 1 is the baseline schema created by the CREATE TABLE statements above.
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial schema: audit_logs and rate_limit_counters", ""),
]


async def _apply_migrations(db: aiosqlite.Connection) -> None:
    await db.execute(_CREATE_SCHEMA_VERSION)
    cursor = await db.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    current: int = row[0] or 0
    for version, description, sql in _MIGRATIONS:
        if version <= current:
            continue
        if sql:
            await db.executescript(sql)
        await db.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, _now_utc()),
        )
        logger.info("Applied DB migration v%d: %s", version, description)
    await db.commit()


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(_CREATE_AUDIT)
        await db.execute(_CREATE_RATE_LIMIT)
        await _apply_migrations(db)
    logger.info("Database ready at %s", settings.db_path)


async def write_audit_log(
    *,
    request_id: str,
    api_key_hash: str,
    model: str,
    provider: str,
    blocked: bool,
    risk_score: int,
    severity: str,
    reasons: list[str],
    latency_ms: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    cost = _compute_cost(model, input_tokens, output_tokens)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """INSERT INTO audit_logs
               (request_id, timestamp, api_key_hash, model, provider, blocked,
                risk_score, severity, reasons, latency_ms, input_tokens, output_tokens, cost_usd)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request_id, _now_utc(), api_key_hash, model, provider,
                int(blocked), risk_score, severity, json.dumps(reasons),
                latency_ms, input_tokens, output_tokens, cost,
            ),
        )
        await db.commit()


async def get_audit_logs(limit: int = 100, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def increment_request_count(api_key_hash: str) -> tuple[int, int]:
    """Increment the request counter for the current minute window.
    Returns (request_count, token_count) after increment.
    Token count reflects tokens accumulated by previous requests this window."""
    window = _minute_window()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """INSERT INTO rate_limit_counters (api_key_hash, window_minute, request_count, token_count)
               VALUES (?, ?, 1, 0)
               ON CONFLICT(api_key_hash, window_minute)
               DO UPDATE SET request_count = request_count + 1""",
            (api_key_hash, window),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT request_count, token_count FROM rate_limit_counters WHERE api_key_hash=? AND window_minute=?",
            (api_key_hash, window),
        )
        row = await cursor.fetchone()
        return (row[0], row[1]) if row else (1, 0)


async def add_token_count(api_key_hash: str, tokens: int) -> None:
    """Record actual token usage after a completed request.
    Called post-response so token totals reflect real usage, not estimates."""
    if tokens <= 0:
        return
    window = _minute_window()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """INSERT INTO rate_limit_counters (api_key_hash, window_minute, request_count, token_count)
               VALUES (?, ?, 0, ?)
               ON CONFLICT(api_key_hash, window_minute)
               DO UPDATE SET token_count = token_count + excluded.token_count""",
            (api_key_hash, window, tokens),
        )
        await db.commit()


# Keep for backwards compatibility
async def increment_rate_counter(api_key_hash: str, tokens: int) -> tuple[int, int]:
    result = await increment_request_count(api_key_hash)
    if tokens > 0:
        await add_token_count(api_key_hash, tokens)
    return result
