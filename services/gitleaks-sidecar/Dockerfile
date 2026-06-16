# Stage 1 — extract the gitleaks binary
FROM ghcr.io/gitleaks/gitleaks:latest AS gitleaks-bin

# Stage 2 — lightweight Python runtime
FROM python:3.11-slim

WORKDIR /app

COPY --from=gitleaks-bin /usr/bin/gitleaks /usr/bin/gitleaks

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
