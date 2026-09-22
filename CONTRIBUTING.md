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
uv run python -m unittest tests.test_router_fine_pitch tests.test_router_ground -v  # routing, ground repair and drill rules
uv run python -m tests.router_regression UNO328C C3BEACON --kicad  # fixed placements; no ignored runs/ or LLM needed
uv run python -m tests.run_offline          # full pipeline with a canned agent answer (needs KiCad for the KiCad DRC step, otherwise skipped)
uv run python -m tests.replay_run <run_id>  # re-place/route/DRC a stored run's design, renders /tmp/etch_<id>_<seed>.png
cd ../frontend && pnpm build                # zero TypeScript errors expected
node screenshots/live.mjs 0                 # drives a real run through the UI with Playwright and saves screenshots
```

`tests.router_regression` without board names checks all six saved fixtures, including the now-complete motor driver.
All six must pass connectivity and error checks; do not suppress a failing result. `--kicad` requires KiCad
and reports its independent connectivity result and warnings. `--grid 0.2` or `--grid 0.1` disables automatic
refinement for comparisons; `--budget` sets the total routing time allowance. Temporary PCB/DRC reports are retained
at the printed paths. The fixture placements and netlists are frozen; the board router does not call the agent.

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
- Router: eliminate remaining narrow copper-connection warnings, local (rather than full-board) grid refinement, staggered fine-pitch
  fan-out, and USB differential-pair / power-width constraints. Preserve the existing minimum track/clearance rules.
- Placement: keep decoupling caps adjacent to their IC pins.
- Frontend: Gerber layer viewer from the actual exported files.

Please keep `PROTOCOL.md` in sync when you add or change events.
