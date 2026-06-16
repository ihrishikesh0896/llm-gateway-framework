"""In-memory runtime state (counters, etc.)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GatewayStats:
    requests_total: int = 0
    requests_blocked: int = 0
    pii_detections: int = 0
    injection_detections: int = 0


stats = GatewayStats()
