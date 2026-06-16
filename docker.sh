#!/usr/bin/env bash
# AI API Gateway — Docker Compose helper
#
# Usage:
#   ./docker.sh [ENV] [COMMAND]
#
# ENV (default: dev):
#   dev      Cloud providers, verbose errors, fail-open sidecars, debug logging
#   local    Ollama only, zero cloud dependency, air-gapped
#   staging  Mirrors prod security, verbose errors on, secrets injected by CI
#   prod     Full hardened mode, secrets injected by secrets manager
#
# COMMAND (default: up):
#   up       Start all services detached
#   down     Stop and remove containers (keeps volumes)
#   destroy  Stop, remove containers AND named volumes
#   build    Build images without cache
#   rebuild  build + up in one step
#   logs     Tail gateway logs (Ctrl-C to exit)
#   ps       Show container statuses and health
#   shell    Open a shell inside the gateway container
#   pull     Pull the latest base images
#
# Examples:
#   ./docker.sh                   # dev env, start detached
#   ./docker.sh local             # local Ollama-only env, start detached
#   ./docker.sh dev logs          # stream gateway logs
#   ./docker.sh staging rebuild   # fresh build + start for staging
#   ./docker.sh prod ps           # check container health in prod

set -euo pipefail

ENV="${1:-dev}"
CMD="${2:-up}"
ENV_FILE=".env.${ENV}"
COMPOSE_FILE="docker-compose.yml"

# ── Validate env ───────────────────────────────────────────────────────────────
VALID_ENVS=("dev" "local" "staging" "prod")
if [[ ! " ${VALID_ENVS[*]} " =~ " ${ENV} " ]]; then
  echo "Error: unknown environment '${ENV}'"
  echo "Valid environments: ${VALID_ENVS[*]}"
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: ${ENV_FILE} not found."
  echo "Copy the template and fill in your values:"
  echo "  cp .env.example ${ENV_FILE}"
  exit 1
fi

# Export so docker-compose.yml can reference ${GATEWAY_ENV_FILE} in env_file: directives
export GATEWAY_ENV_FILE="${ENV_FILE}"
DC="docker compose --env-file ${ENV_FILE} -f ${COMPOSE_FILE}"

echo "→ env: ${ENV}  |  file: ${ENV_FILE}  |  cmd: ${CMD}"
echo ""

# ── Commands ───────────────────────────────────────────────────────────────────
case "${CMD}" in
  up)
    ${DC} up -d
    echo ""
    echo "Stack is up. Service status:"
    ${DC} ps
    echo ""
    echo "Gateway: http://localhost:8000"
    echo "Health:  http://localhost:8000/gateway/health"
    echo "Metrics: http://localhost:8000/metrics"
    ;;

  down)
    ${DC} down --remove-orphans
    ;;

  destroy)
    echo "WARNING: This will delete all volumes including the SQLite audit DB."
    read -r -p "Are you sure? [y/N] " confirm
    if [[ "${confirm}" =~ ^[Yy]$ ]]; then
      ${DC} down --remove-orphans --volumes
    else
      echo "Aborted."
    fi
    ;;

  build)
    ${DC} build --no-cache
    ;;

  rebuild)
    ${DC} down --remove-orphans
    ${DC} build --no-cache
    ${DC} up -d
    echo ""
    ${DC} ps
    ;;

  logs)
    ${DC} logs -f gateway
    ;;

  ps)
    ${DC} ps
    ;;

  shell)
    ${DC} exec gateway /bin/bash
    ;;

  pull)
    ${DC} pull
    ;;

  *)
    echo "Error: unknown command '${CMD}'"
    echo ""
    echo "Usage: $0 [dev|local|staging|prod] [up|down|destroy|build|rebuild|logs|ps|shell|pull]"
    exit 1
    ;;
esac
