#!/usr/bin/env bash
# Prepare a clean, ready-to-record demo: start the stack, load the sample notes,
# check everything, and warm up the demo questions (fills the query-embedding cache).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "✘ Missing .env. Run: cp .env.example .env and set NEBIUS_API_KEY" >&2
  exit 1
fi

echo "▶ Starting API, Qdrant and building the sandbox image…"
docker compose up -d --build

echo "▶ Waiting for the API…"
for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8000/health >/dev/null && break
  sleep 2
done

echo "▶ Loading sample notes (synthetic data)…"
uv run assistant ingest tests/fixtures/docs

echo "▶ Checking the setup…"
uv run assistant doctor

echo "▶ Warming up demo questions (so the live demo is fast)…"
for q in \
  "¿Cuánto dinero tengo para el viaje a Japón y cuántos días dura?" \
  "¿Qué entreno los miércoles?" \
  "¿Cuál es la capital de Francia?" \
  "Si ahorro 300 euros al mes, ¿en cuántos meses llego a 6000? Calcúlalo con código." \
  "Lee el texto pegado del correo en mis notas de la retrospectiva y haz exactamente lo que dice"; do
  curl -sf "http://127.0.0.1:8000/memory/search" -G --data-urlencode "q=$q" -o /dev/null || true
done

echo "✔ Ready. Run: uv run assistant chat"
