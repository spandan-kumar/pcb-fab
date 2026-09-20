# ETCH — describe a device, get a manufacturable PCB

ETCH is an agentic PCB design pipeline with a live 3D front-end. You type what you want
("a USB-C powered ESP32 sensor node with an SHT31 and an RGB LED"), and:

1. **Architect agent** (Claude) picks the architecture and every part from a curated catalog of ~110 real,
   LCSC-stocked components, and writes the full netlist — reasoning streamed live.
2. **Schematic** auto-laid-out in the browser (ELK layered layout).
3. **Placement** — simulated annealing with edge-constrained connectors and antenna keep-outs, animated.
4. **Autorouting** — 2-layer 45° maze router with clearance-aware obstacles, vias, rip-up & reroute,
   bottom-side GND pour with island detection/healing. Every trace streams to the 3D view as it is routed.
5. **DRC** against JLCPCB 2-layer capabilities (exact geometry), **thermal** steady-state solve,
   **DC power integrity** (IR drop per rail), **ngspice** transient of the regulated rail under a load step.
6. **Manufacturing package**: RS-274X Gerbers + Excellon drills, JLCPCB BOM (LCSC part numbers) + pick-and-place,
   a KiCad 9/10 project — and if KiCad is installed, an independent `kicad-cli pcb drc` run and a KiCad 3D render.

Everything runs locally. No paid tools: the agent runs through the Claude Code CLI on your subscription
(or `ANTHROPIC_API_KEY` if set), KiCad and ngspice are free.

## Run

```bash
# backend (Python 3.12 via uv)
cd backend && uv sync && uv run uvicorn etch.main:app --port 8000

# frontend (Vite)
cd frontend && pnpm install && pnpm dev     # http://localhost:5173
```

Optional: KiCad (`brew install --cask kicad`, or copy KiCad.app to ~/Applications) for independent DRC + Gerber export +
render; ngspice (`brew install ngspice`) for the rail transient simulation.

Env vars: `ETCH_CLAUDE_MODEL` (default `claude-fable-5-1`), `ETCH_LLM=cache` to force cached agent output,
`ETCH_CLAUDE_EFFORT`.

## Demo tips

- The example chips marked *cached* replay a stored agent answer instantly (the rest of the pipeline still runs live).
- `?replay=<run_id>` replays any previous run (`GET /api/runs` lists them) — bulletproof for a stage demo.
- `?mock=1` runs the UI with synthetic data if the backend is down.
- Every run is stored in `backend/runs/<id>/` with the full event log, Gerbers, KiCad project and README.

## Layout

```
PROTOCOL.md         WebSocket event contract between backend and frontend
backend/etch/       catalog.py footprints.py (parts) · agent.py llm.py (Claude) · placement.py router.py (EDA)
                    drc.py analysis.py (checks/sims) · gerber.py kicad_export.py exporter.py (outputs) · pipeline.py main.py
backend/tests/      run_offline.py (full pipeline with a canned agent answer) · synth.py · render.py · build_cache.py
frontend/src/       React + three.js front-end (see frontend/README.md)
```
