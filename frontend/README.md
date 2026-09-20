# ETCH frontend

Vite + React + TypeScript + three.js (react-three-fiber) UI for the ETCH engine. Implements `/PROTOCOL.md` exactly.

```bash
pnpm install
pnpm dev          # http://localhost:5173  (proxies /api and /ws → localhost:8000)
pnpm build        # type-check + production bundle in dist/
```

## URL flags

| flag | effect |
|---|---|
| `?mock=1` | run a built-in synthetic design (no backend needed) |
| `?replay=<run_id>` | replay `/api/runs/<run_id>/events.json` with original timing |
| `&speed=2` | replay/mock speed multiplier (also switchable in the top bar: 0.5×/1×/2×/5×) |
| `&color=green` | solder-mask colour for mock |
| `&nofx` | disable bloom post-processing |

## Layout

- `src/protocol.ts` – event/type definitions (mirror of PROTOCOL.md)
- `src/store.ts` – zustand store, single `applyEvent()` reducer; live, replay and mock all go through it
- `src/live.ts` – mutable per-frame state (component lerp targets, trace animation queue) — never triggers React renders
- `src/ws.ts` – WebSocket client, replay player, mock runner
- `src/three/BoardScene.tsx` – 3D board (substrate, pads, animated traces, vias, GND pour, parts, ratsnest, DRC markers, thermal overlay, layer explode)
- `src/three/Effects.tsx` – bloom via three's own EffectComposer/UnrealBloomPass
- `src/schematic/Schematic.tsx` – ELK-layered SVG schematic with net-label flags
- `src/components/*` – Landing, Workspace, AgentPanel, Viewport, StatsPanel
- `src/mock/mockRun.ts` – synthetic event stream
- `screenshots/*.mjs` – playwright capture scripts (`node screenshots/seq.mjs "<url>" screenshots/out "5000,10000"`)

Screenshots are captured with `--use-angle=metal` (headless swiftshader can't allocate the WebGL drawing buffer for this scene).
