# Contributing

Thanks for taking a look. ETCH is a hackathon project that grew a real EDA core; contributions are very welcome.

## Dev setup

```bash
cd backend && uv sync && uv run uvicorn etch.main:app --port 8000   # Python 3.12
cd frontend && pnpm install && pnpm dev                                # http://localhost:5173
```

Fast checks that don't need an LLM:

```bash
cd backend
uv run python -m tests.run_offline          # full pipeline with a canned agent answer (needs KiCad for the KiCad DRC step, otherwise skipped)
uv run python -m tests.replay_run <run_id>  # re-place/route/DRC a stored run's design, renders /tmp/etch_<id>_<seed>.png
cd ../frontend && pnpm build                # zero TypeScript errors expected
node screenshots/live.mjs 0                 # drives a real run through the UI with Playwright and saves screenshots
```

## Where things live

| Area | Files |
|---|---|
| Parts & footprints | `backend/etch/catalog.py`, `backend/etch/footprints.py` |
| Agent prompt / validation | `backend/etch/agent.py`, `backend/etch/llm.py` |
| Placement / routing | `backend/etch/placement.py`, `backend/etch/router.py` |
| Checks & sims | `backend/etch/drc.py`, `backend/etch/analysis.py` |
| Outputs | `backend/etch/gerber.py`, `backend/etch/kicad_export.py`, `backend/etch/exporter.py` |
| Orchestration / API | `backend/etch/pipeline.py`, `backend/etch/main.py`, `PROTOCOL.md` |
| UI | `frontend/src` (React + three.js, event-driven zustand store) |

## Good first issues

- More catalog parts (each needs a pinout, a footprint and ideally an LCSC number).
- Router: staggered escape pattern for 0.5 mm pitch connectors, finer grid near fine-pitch pads, smarter rip-up ordering.
- Placement: keep decoupling caps adjacent to their IC pins.
- Frontend: Gerber layer viewer from the actual exported files.

Please keep `PROTOCOL.md` in sync when you add or change events.
