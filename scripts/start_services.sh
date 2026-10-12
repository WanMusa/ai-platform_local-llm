#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
    echo "ERROR: Create the VPS .env from .env.example before starting." >&2
    exit 1
fi

# Quiet validation avoids printing resolved credentials.
docker compose config --quiet
docker network inspect ai_platform >/dev/null 2>&1 || docker network create ai_platform

docker compose up -d ollama --wait --wait-timeout 180
echo "Checking/provisioning the configured model (up to 30 minutes)..."
if ! timeout 1800 docker compose exec -T ollama sh -c \
    'ollama show "$LLM_MODEL" >/dev/null 2>&1 || ollama pull "$LLM_MODEL"'; then
    echo "ERROR: Model provisioning failed or exceeded 30 minutes. Check Ollama logs and rerun." >&2
    exit 1
fi

docker compose up -d --build --remove-orphans --wait --wait-timeout 180
echo "Services healthy; health checks do not prove model inference or HTTPS."
