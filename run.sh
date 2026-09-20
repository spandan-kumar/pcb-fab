#!/usr/bin/env bash
# Start ETCH backend (:8000) and frontend (:5173)
set -e
cd "$(dirname "$0")"
(cd backend && uv sync -q && uv run uvicorn etch.main:app --host 0.0.0.0 --port 8000 &) 
(cd frontend && pnpm install --silent && pnpm dev --host &)
sleep 2
echo "ETCH → http://localhost:5173"
wait
