"""Gitleaks sidecar — thin HTTP wrapper around the gitleaks binary."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Gitleaks Sidecar", version="1.0.0")

_GITLEAKS_BIN = "/usr/bin/gitleaks"
_RULES_FILE = Path("/app/gitleaks_rules.toml")

_RULE_WEIGHTS: dict[str, int] = {}


@app.on_event("startup")
def _load_weights() -> None:
    global _RULE_WEIGHTS
    try:
        import tomllib
        with open(_RULES_FILE, "rb") as f:
            data = tomllib.load(f)
        _RULE_WEIGHTS = {r["id"]: r.get("weight", 40) for r in data.get("rules", [])}
    except Exception as exc:
        print(f"Warning: could not load rule weights: {exc}")


class ScanRequest(BaseModel):
    text: str


class SecretFinding(BaseModel):
    rule_id: str
    description: str
    weight: int
    secret_snippet: str


class ScanResponse(BaseModel):
    findings: list[SecretFinding]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest) -> ScanResponse:
    if not req.text.strip():
        return ScanResponse(findings=[])

    # TemporaryDirectory ensures atomic cleanup and eliminates TOCTOU risk.
    # All temp paths are generated internally — no user input touches the path.
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.txt")
        report_path = os.path.join(tmpdir, "report.json")

        with open(input_path, "w", encoding="utf-8") as f:
            f.write(req.text)

        try:
            subprocess.run(
                [
                    _GITLEAKS_BIN, "detect",
                    "--no-git",
                    "--source", input_path,
                    "--config", str(_RULES_FILE),
                    "--report-format", "json",
                    "--report-path", report_path,
                    "--exit-code", "0",
                    "--log-level", "error",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,  # exit code 1 = leaks found, not an error
            )

            try:
                with open(report_path) as f:
                    raw = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                raw = []

            findings: list[SecretFinding] = []
            seen: set[str] = set()
            for hit in (raw or []):
                rule_id = hit.get("RuleID", "unknown")
                if rule_id in seen:
                    continue
                seen.add(rule_id)
                secret = hit.get("Secret", "") or hit.get("Match", "")
                findings.append(SecretFinding(
                    rule_id=rule_id,
                    description=hit.get("Description", rule_id),
                    weight=_RULE_WEIGHTS.get(rule_id, 40),
                    secret_snippet=secret[:6] + "..." if len(secret) > 6 else secret,
                ))

            return ScanResponse(findings=findings)

        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Gitleaks scan timed out")
