"""Risk score computation from pipeline findings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.pipeline.base import Finding


@dataclass
class RiskAssessment:
    score: int                                            # 0-100
    severity: Literal["low", "medium", "high", "critical"]
    reasons: list[str]


def compute_risk_score(findings: list[Finding]) -> RiskAssessment:
    score = min(100, sum(f.weight for f in findings))
    severity: Literal["low", "medium", "high", "critical"]
    if score >= 76:
        severity = "critical"
    elif score >= 51:
        severity = "high"
    elif score >= 26:
        severity = "medium"
    else:
        severity = "low"
    reasons = list(dict.fromkeys(f.label for f in findings))  # deduplicate, preserve order
    return RiskAssessment(score=score, severity=severity, reasons=reasons)
