# ETCH — describe a device, get a manufacturable PCB

> An agentic PCB design pipeline with a live 3D front-end. Type what you want to build; an AI hardware architect
> picks the parts, writes the netlist, and a from-scratch EDA engine places, routes, checks, simulates and exports
> a fab-ready 2-layer board — every step streamed and animated in the browser.

**Live demo:** https://pcb-fab.vercel.app — the UI on Vercel with four recorded runs you can replay (the design engine itself runs locally; see [Deploying](#deploying)).

![ETCH finished board](docs/board-3d.png)

```
"A USB-C powered ESP32 environmental sensor node with an SHT31, a BME280,
 a WS2812B status LED, boot/reset buttons and a Qwiic connector."
```
→ 80 seconds later: 33 parts, 17 nets, 605 mm of copper, 66 vias, 0 DRC errors, KiCad DRC PASS,
Gerbers + BOM + pick-and-place + KiCad project in a zip.

## What happens when you press FORGE

| Stage | What runs | What you see |
|---|---|---|
| **Architect** | Claude reads the brief and designs the board from a curated catalog of ~110 real, LCSC-stocked parts (pinouts, footprints, design hints). Output is validated and repaired into a netlist. | Engineering reasoning streams live; component cards fly in. |
| **Schematic** | ELK layered layout in the browser: ports on the right sides, orthogonal wires, power flags & GND bars like a real schematic. | Wires draw themselves; hover highlights a net (also in 3D). |
| **Placement** | Simulated annealing with edge-constrained connectors, antenna keep-outs, courtyard repulsion. Six seeds anneal in parallel and get test-routed; the best wins. | Parts drop onto the board and settle. |
| **Routing** | 2-layer 45° maze router: 0.2 mm grid with a bounded 0.1 mm refinement pass for incomplete fine-pitch boards, clearance-aware obstacles, escape stubs, multi-level rip-up & reroute, bottom GND pour with island healing. | Every trace draws in with a glowing routing head; routing retries reset the previous copper before replaying the selected result. |
| **DRC** | Exact-geometry check against JLCPCB 2-layer rules: clearance, width, drill/annular ring, edge clearance, courtyards, connectivity. | Checklist + clickable violation markers on the board. |
| **Thermal / Power / SPICE** | Steady-state heat solve, DC IR-drop per rail from the actual copper, and an **ngspice** transient of the regulated rail under a load step using the board's real decoupling. | Animated heatmap, rail table, oscilloscope-style chart. |
| **Export** | RS-274X Gerbers (X2), Excellon drills, JLCPCB BOM & CPL, a KiCad 9/10 project — then an independent `kicad-cli pcb drc` and a KiCad 3D render of the same board. | Download buttons, "KiCad verified" badge, render thumbnail. |

<p align="center">
<img src="docs/routing.png" width="49%"> <img src="docs/thermal.png" width="49%"><br>
<img src="docs/schematic.png" width="49%"> <img src="docs/kicad-render.png" width="49%">
</p>

Everything runs locally and everything is free: the agent runs through the Claude Code CLI on your own subscription
(or `ANTHROPIC_API_KEY` if set), KiCad and ngspice are open source.

## Quick start

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 20+ with pnpm, and the
[Claude Code CLI](https://claude.com/claude-code) logged in (`claude -p "hi"` should answer).
Optional but recommended: [KiCad 9/10](https://kicad.org) (independent DRC + Gerber export + render) and
`ngspice` (`brew install ngspice`).

```bash
git clone https://github.com/spandan-kumar/pcb-fab.git && cd pcb-fab
./run.sh                    # starts backend :8000 and frontend :5173
# or separately:
cd backend  && uv sync && uv run uvicorn etch.main:app --port 8000
cd frontend && pnpm install && pnpm dev
```

Open http://localhost:5173, pick an example chip or type your own brief, press **FORGE IT**.

### Demo-safe modes

- Example prompts marked *cached* replay a stored agent answer instantly; the rest of the pipeline still runs live.
  Pass `{"force_live": true}` in the start options to call the model anyway.
- `?replay=<run_id>` replays any previous run event-for-event (`GET /api/runs` lists them, with speed controls 0.5×–5×).
- `?mock=1` runs the UI on synthetic data when the backend is down.
- Every run is stored in `backend/runs/<id>/` with the full event log, Gerbers, KiCad project, README and render.

### Environment

| Variable | Default | Meaning |
|---|---|---|
| `ETCH_CLAUDE_MODEL` | `claude-fable-5-1` | Model for the Claude CLI backend (Opus 5's safety classifier false-positives on the catalog prompt; Sonnet is used as fallback). |
| `ETCH_LLM` | auto | `cache` forces cached agent output only. |
| `ANTHROPIC_API_KEY` | — | If set, the Anthropic SDK is used instead of the CLI. |
| `ETCH_PROMPT_VERSION` | `1` | Bump to invalidate the demo cache. |

## Results on the bundled examples

Fixed-placement reroutes with the current engine and KiCad 10.0.6 (parts include mounting holes).
These results are reproducible from `backend/tests/fixtures/router_boards.json`; the recorded frontend demos are not regenerated by a router code change.

| Example | Parts | Routed | ETCH DRC | KiCad 10 DRC |
|---|---|---|---|---|
| ESP32 environmental node | 33 | 100 % | 0 errors | PASS |
| LiPo ESP32-C3 beacon | 38 | 100 % | 0 errors | PASS |
| ESP32-S3 data logger | 35 | 100 % | 0 errors | PASS |
| RS-485 industrial node | 42 | 100 % | 0 errors | PASS |
| Dual-motor robot driver | 42 | 100 % | 0 errors | PASS (0 warnings) |
| Arduino-style AVR board | 34 | 100 % | 0 errors | PASS |

The AVR board previously left three nets unrouted; it now completes. The motor board now completes too, including
the two ground connections that previously failed KiCad's independent check. The router retains a successful coarse route, retries incomplete
fine-pitch boards at 0.1 mm within the same time budget, and keeps the better DRC result. Rip-ups respect the actual
copper layer and clearance, and GND repair preserves shared stubs and recognizes top-layer bridges between islands.
Ground connectivity accounts for the zone's 0.25 mm minimum copper thickness; narrow necks that disappear during
KiCad filling no longer count as connections. Repairs can use the existing 0.2 mm escape width when 0.3 mm will not fit.
Existing vias are reused without duplicate drill holes, and the router and local DRC share KiCad's 0.5 mm hole-spacing rule.
The 0.2 mm minimum track width and 0.18 mm routing clearance have not been relaxed.

PASS means no KiCad errors or unconnected items, not zero warnings: four fixtures still have narrow copper-connection
warnings (ENVNODE32: 1, C3BEACON: 2, S3LOGGER: 2, UNO328C: 2). ROBODRIVES3 and RS485NODE have none.
No fixture has coincident/nearby-hole warnings. Inspect the exported KiCad report before fabrication. See [Limitations](#limitations).

## How it works

```
frontend (React + three.js)  ⇄  WebSocket /ws/design  ⇄  backend (FastAPI)
                                                              │
   brief → architect (Claude) → components → netlist → placement trials (multiprocess)
         → placement replay → router → DRC → thermal → power/spice → export (Gerber, KiCad, BOM, zip)
```

The whole system is event-driven: the backend emits a typed event stream (see [`PROTOCOL.md`](PROTOCOL.md)), the
frontend is a pure reducer over those events, so live runs, replays and mocks share one code path.

```
PROTOCOL.md          event contract
backend/etch/
  catalog.py         parts: pinouts, footprints, LCSC ids, design hints (fed to the agent as its parts list)
  footprints.py      parametric footprint generators (0402…1206, SOT, SOIC/TSSOP/QFP/QFN, modules, connectors, THT)
  agent.py llm.py    system prompt, streaming (Claude CLI / SDK / cache), JSON validation & repair → Board
  placement.py       simulated annealing, edge constraints, ratsnest
  router.py          grid maze router (A*, 8-dir, vias), escape stubs, rip-up/reroute, pour islands
  drc.py             exact-geometry design rule check (JLCPCB 2-layer)
  analysis.py        thermal solve, IR drop, ngspice rail transient
  gerber.py          RS-274X + Excellon writer (incl. negative-plane GND pour), stroke-font silkscreen
  kicad_export.py    .kicad_pcb / .kicad_pro writer, kicad-cli DRC / gerbers / render
  exporter.py        BOM, CPL, netlist, README, zip packaging
  pipeline.py        orchestration + event emission;  main.py: FastAPI/WebSocket
backend/tests/       run_offline.py (no-LLM full pipeline), replay_run.py, render.py, build_cache.py
frontend/src/        store.ts (reducer), three/ (board scene, effects), schematic/ (ELK), components/
```

### Design rules used

Trace 0.2–0.6 mm by net class, routing clearance 0.18 mm, vias 0.6/0.3 mm, copper-to-edge 0.5 mm, 1.6 mm FR-4,
1 oz copper. Checked against JLCPCB minimums (0.127 mm trace/clearance, 0.3 mm drill, 0.13 mm annular ring).

## Limitations

- **Dense layouts still need review.** USB-C, LQFP-48 and QFN 0.5 mm escape regressions pass, with 0.1 mm refinement
  available when the coarse pass cannot finish. This is not a guarantee for arbitrary placements, smaller pitches or BGAs.
  Refinement uses more CPU/memory; local adaptive grids and staggered fan-out are still future work.
- **Bounded repair.** Rip-up can recurse through three levels while protecting the nets being repaired. It remains
  time-limited and can leave congested nets or GND islands unresolved on other placements. The conservative pour model
  is not a substitute for KiCad's independent zone-fill/connectivity check.
- **Footprints are parametric approximations** of the real packages — good enough for DRC-clean boards, but check the
  connector footprints against the manufacturer drawings before ordering.
- **No schematic file.** The schematic is a browser view; the netlist is exported as JSON and inside the `.kicad_pcb`.
- The thermal and SPICE models are deliberately simple first-order models meant to catch gross problems, not sign-off tools.

## Deploying

The front-end is a static Vite build and lives on Vercel (`frontend/vercel.json`): https://pcb-fab.vercel.app.
It ships with the recorded runs in `frontend/public/demo/` so replays, Gerber downloads and KiCad renders work with no
backend at all. The engine (FastAPI + WebSockets, multi-minute CPU jobs, KiCad, ngspice, the Claude CLI) needs a real
machine — run it locally or on any VM/container and point the UI at it:

```bash
cd frontend && vercel env add VITE_BACKEND_URL production   # e.g. https://etch.yourdomain.com  (or an ngrok/cloudflared tunnel to localhost:8000)
vercel --prod
```

Without `VITE_BACKEND_URL` the UI uses its own origin (`/api`, `/ws`), which is what the Vite dev proxy expects.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Next priorities: remove narrow copper-connection warnings,
add local fan-out/USB pair and power-width constraints, improve cap-to-IC adjacency, and display the actual exported Gerbers.

## License

MIT — see [LICENSE](LICENSE). Built with Claude Code during a hackathon; the EDA core (placer, router, DRC, Gerber and
KiCad writers) is original code with no external EDA dependencies.
