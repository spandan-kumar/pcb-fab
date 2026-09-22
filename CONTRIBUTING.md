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
uv run python -m unittest discover -s tests -p 'test_router_*.py' -v  # routing, power widths, junctions, ground repair and drill rules
uv run python -m unittest tests.test_refresh_demos -v  # offline guards, saved designs and replay/export consistency
uv run python -m tests.router_regression --strict-kicad --strict-power  # six fixed placements; zero KiCad errors/warnings/unconnected items and all power-width targets met
uv run python -m tests.run_offline          # full pipeline with a canned agent answer (needs KiCad for the KiCad DRC step, otherwise skipped)
uv run python -m tests.replay_run <run_id>  # re-place/route/DRC a stored run's design, renders /tmp/etch_<id>_<seed>.png
cd ../frontend && pnpm build                # zero TypeScript errors expected
node screenshots/live.mjs 0                 # drives a real run through the UI with Playwright and saves screenshots
```

`tests.router_regression` without board names checks all six saved fixtures, including the now-complete motor driver.
All six must pass connectivity and error checks; do not suppress a failing result. `--strict-kicad` also requires
zero KiCad warnings; use it to catch narrow copper-junction regressions. `--kicad` reports warnings without failing on them.
Both require KiCad to be available. `--grid 0.2` or `--grid 0.1` disables automatic
refinement for comparisons; `--budget` sets the total routing time allowance. Temporary PCB/DRC reports are retained
at the printed paths. The fixture placements and netlists are frozen; the board router does not call the agent.

`--strict-power` independently fails on unmet current-class width targets. Reports include each power rail's target,
allowed pad neck-down length and remaining constrained length. All 18 rails in the six fixtures now pass; require
both strict flags for router changes. Other placements can still report width warnings: do not suppress them or
treat a clean KiCad report as proof of current capacity. Tests cover full-width detours, power-first ordering,
transactional width refinement, spacing between new vias in a path, variable-width occupancy after rip-up,
reserved escapes, holes/edges, layer-specific pad allowances, and low voltage drop not masking a width failure.

`test_router_clearance.py` compares the optimized disk expansion with the original offset-by-offset calculation,
including strict radius boundaries, board edges, narrow arrays, and protected/soft/via masks on both grids.
Performance changes must preserve those masks. The regression report's `seconds` field measures routing (excluding
KiCad export); compare runs on the same machine without concurrent CPU-heavy work.

## Refreshing the four demos without API credits

From `backend`, run `uv run python -m tests.refresh_demos --output /tmp/etch-demos-new` using a
new, nonexistent output directory. KiCad and ngspice must be installed. The command reads the
bundled packages' `design.json` and `netlist.json`, preserving components, full-precision placements,
netlists and board text. It does not import or invoke the agent, re-place parts, or call any API.
Python network connections and non-KiCad/ngspice subprocesses are blocked during the rebuild.

Routing events, thermal/power/SPICE analyses, KiCad projects, both Gerber packages and top renders
are regenerated together. Publication fails if copper events disagree with the final board, routing
is incomplete, power-width/drop checks fail, either DRC reports warnings/errors, KiCad finds
unconnected items, or an export is missing. Sources are untouched; the output manifest is written
only after every board passes. `refresh.json` in each package records its source package hash, base Git
commit and engine source hash (including any local engine changes).
Pre-routing design/placement events are explicitly archived; replay time combines their old timestamps
with measured rebuild time, not the duration of a new agent run.

For frontend-only QA, build the frontend, copy the staged bundle into `frontend/dist/demo/`, then
run `pnpm preview --host 127.0.0.1` and `node screenshots/demo-replay.mjs http://127.0.0.1:4173`
from `frontend`. The check blocks backend requests and exercises all four cards, width results,
renders and both download buttons. After QA, replace the corresponding `frontend/public/demo/`
bundle and rebuild. New replay IDs prevent old cached events, renders and ZIPs from mixing with
new exports; old recordings remain available in Git history. Never publish a partial output directory.

## Where things live

| Area | Files |
|---|---|
| Parts & footprints | `backend/etch/catalog.py`, `backend/etch/footprints.py` |
| Agent prompt / validation | `backend/etch/agent.py`, `backend/etch/llm.py` |
| Placement / routing | `backend/etch/placement.py`, `backend/etch/router.py`, `backend/etch/power_routing.py` |
| Checks & sims | `backend/etch/drc.py`, `backend/etch/analysis.py` |
| Outputs | `backend/etch/gerber.py`, `backend/etch/kicad_export.py`, `backend/etch/exporter.py` |
| Orchestration / API | `backend/etch/pipeline.py`, `backend/etch/main.py`, `PROTOCOL.md` |
| UI | `frontend/src` (React + three.js, event-driven zustand store) |

## Good first issues

- More catalog parts (each needs a pinout, a footprint and ideally an LCSC number).
- Router: branch-current/via-capacity modelling, shorter bounded searches on dense boards,
  USB differential-pair constraints, local (rather than full-board) grid refinement and staggered fine-pitch fan-out.
  Preserve the existing minimum track/clearance rules and zero-KiCad-warning fixtures.
- Placement: keep decoupling caps adjacent to their IC pins.
- Frontend: Gerber layer viewer from the actual exported files.

Please keep `PROTOCOL.md` in sync when you add or change events.
