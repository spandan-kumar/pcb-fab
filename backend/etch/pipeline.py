"""Design pipeline: agent → placement → routing → DRC → thermal/power/spice → export. Emits protocol events."""
from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
import uuid
from typing import Awaitable, Callable

from . import agent, llm
from .analysis import ngspice_available, power_rails, spice_rail_step, thermal
from .drc import run_drc
from .exporter import export_all
from .kicad_export import kicad_cli
from .model import Board
from .placement import Placer, ratsnest
from .router import Router

RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "runs")
os.makedirs(RUNS_DIR, exist_ok=True)

STAGES = ["brief", "architect", "components", "netlist", "schematic", "placement", "routing", "drc", "thermal", "power", "export"]


class Run:
    def __init__(self, send: Callable[[dict], Awaitable[None]]):
        self.id = uuid.uuid4().hex[:10]
        self.dir = os.path.join(RUNS_DIR, self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.t0 = time.time()
        self.seq = 0
        self.events: list[dict] = []
        self._send = send
        self.loop = asyncio.get_event_loop()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.cancelled = False

    async def emit(self, ev: dict):
        self.seq += 1
        ev = {**ev, "seq": self.seq, "t": round(time.time() - self.t0, 3)}
        self.events.append(ev)
        await self._send(ev)

    def emit_threadsafe(self, ev: dict):
        """Called from worker threads: hand the event to the event loop."""
        self.loop.call_soon_threadsafe(self.queue.put_nowait, ev)

    async def drain(self):
        while not self.queue.empty():
            await self.emit(self.queue.get_nowait())

    async def run_blocking(self, fn, *args):
        """Run a CPU-heavy stage in a thread while forwarding its events."""
        fut = self.loop.run_in_executor(None, fn, *args)
        while not fut.done():
            await self.drain()
            await asyncio.sleep(0.02)
        await self.drain()
        return fut.result()

    async def status(self, stage: str, state: str, message: str = ""):
        await self.emit({"type": "status", "stage": stage, "state": state, "message": message})

    def save(self):
        with open(os.path.join(self.dir, "events.json"), "w") as f:
            json.dump(self.events, f)


async def design(prompt: str, options: dict, send: Callable[[dict], Awaitable[None]]) -> Run:
    run = Run(send)
    color = options.get("color", "black")
    demo = bool(options.get("demo", False))
    await run.emit({"type": "run", "run_id": run.id, "prompt": prompt, "options": options,
                    "backend": llm.backend_name(), "kicad": bool(kicad_cli()), "ngspice": ngspice_available()})
    try:
        # ---------------- brief
        await run.status("brief", "start", "Reading the brief")
        await run.emit({"type": "thought", "text": f"**Brief:** {prompt.strip()}\n\n"})
        await asyncio.sleep(0.3)
        await run.status("brief", "done")

        # ---------------- architect (LLM)
        await run.status("architect", "start", f"Agent thinking ({llm.backend_name()})")
        n_thought = 0

        async def on_thought(t: str):
            nonlocal n_thought
            n_thought += 1
            await run.emit({"type": "thought", "text": t})

        board, design_json, raw = await agent.run_agent(prompt, color, on_thought, prefer_cache=demo)
        with open(os.path.join(run.dir, "agent_output.md"), "w") as f:
            f.write(raw)
        await run.emit({"type": "design", "design": design_json})
        await run.status("architect", "done", f"{design_json['name']}: {len(board.components)} parts, {len(board.nets)} nets")

        # ---------------- components (streamed for the UI)
        await run.status("components", "start", "Selecting components")
        for c in board.components:
            await run.emit({"type": "component", "component": c.to_json()})
            await asyncio.sleep(0.06)
        await run.status("components", "done", f"{len(board.components)} components, est. ${design_json['estimated_cost_usd']:.2f}")

        # ---------------- netlist
        await run.status("netlist", "start", "Building netlist")
        await run.emit({"type": "netlist", "nets": [n.to_json() for n in board.nets]})
        await run.status("netlist", "done", f"{len(board.nets)} nets, {sum(len(n.pins) for n in board.nets)} pins")

        # ---------------- schematic (laid out client-side) — meanwhile: silent placement/routing trials to pick the best seed
        await run.status("schematic", "start", "Laying out schematic · evaluating placements")
        await run.emit({"type": "thought", "text": "\n\n**Placement search.** Trying candidate placements and test-routing each one…\n"})

        def trial(seed: int):
            for c in board.components:
                if not c.fixed:
                    c.x = c.y = 0.0
            board.traces.clear()
            board.vias.clear()
            Placer(board, seed=seed).run(frames=1)
            r = Router(board, time_budget=40)
            res = r.route_all()
            return res

        best = None
        for seed in (7, 3, 11, 19, 23):
            res = await run.run_blocking(trial, seed)
            score = (len(res["failed"]), res["orphan_gnd"], res["ripups"], res["length_mm"])
            await run.emit({"type": "thought", "text": f"- seed {seed}: {len(res['failed'])} unrouted, {res['orphan_gnd']} plane islands, "
                                                       f"{res['ripups']} rip-ups, {res['length_mm']} mm copper, {res['vias']} vias\n"})
            if best is None or score < best[0]:
                best = (score, seed)
            if score[0] == 0 and score[1] == 0:
                break
        best_seed = best[1]
        await run.emit({"type": "thought", "text": f"→ using seed {best_seed}.\n"})
        board.traces.clear()
        board.vias.clear()
        for c in board.components:
            if not c.fixed:
                c.x = c.y = 0.0
        await run.status("schematic", "done")

        # ---------------- placement
        await run.status("placement", "start", f"Placing {len(board.components)} parts on {board.width}×{board.height} mm")
        await run.emit({"type": "board", "board": board.to_json()})
        await asyncio.sleep(0.8)

        def do_place():
            placer = Placer(board, seed=best_seed)
            last = {"t": 0.0}

            def on_frame(it, total, T, cost):
                now = time.time()
                if now - last["t"] < 0.03 and it != total:
                    return
                last["t"] = now
                run.emit_threadsafe({"type": "placement", "iteration": it, "total": total, "temperature": round(T, 3), "cost": round(cost, 1),
                                     "positions": {c.ref: [round(c.x, 3), round(c.y, 3), c.rot] for c in board.components}})

            placer.run(on_frame=on_frame, frames=70)
            return placer

        await run.run_blocking(do_place)
        await run.emit({"type": "placement_final", "positions": {c.ref: [round(c.x, 3), round(c.y, 3), c.rot] for c in board.components}})
        await run.emit({"type": "ratsnest", "lines": ratsnest(board)})
        await run.status("placement", "done")
        await asyncio.sleep(0.6)

        # ---------------- routing
        n_routable = len([n for n in board.nets if len(n.pins) >= 2])
        await run.status("routing", "start", f"Routing {n_routable} nets")
        router_holder = {}

        def do_route():
            r = Router(board, on_event=run.emit_threadsafe, time_budget=float(options.get("route_budget_s", 200)))
            router_holder["r"] = r
            return r.route_all()

        route_res = await run.run_blocking(do_route)
        router = router_holder["r"]
        keepouts = _keepouts(board)
        await run.status("routing", "done", f"{route_res['length_mm']} mm of copper, {route_res['vias']} vias, {route_res['ripups']} rip-ups")

        # ---------------- DRC
        await run.status("drc", "start", "Running design rule check")
        drc = await run.run_blocking(run_drc, board, route_res["failed"], route_res["orphan_gnd"])
        await run.emit({"type": "drc", **drc})
        await run.status("drc", "done" if drc["passed"] else "error", f"{drc['errors']} errors, {drc['warnings']} warnings")

        # ---------------- thermal
        await run.status("thermal", "start", "Solving steady-state thermal field")
        therm = await run.run_blocking(thermal, board, run.emit_threadsafe)
        await run.status("thermal", "done", f"Hotspot {therm['max_c']} °C")

        # ---------------- power (+ spice)
        await run.status("power", "start", "DC power integrity")
        rails = power_rails(board)
        await run.emit({"type": "power", "rails": rails})
        sp = await run.run_blocking(spice_rail_step, board)
        if sp:
            await run.emit(sp)
        await run.status("power", "done", f"{len(rails)} rails analysed" + (", ngspice transient OK" if sp else ""))

        # ---------------- export
        await run.status("export", "start", "Writing Gerbers, drill, BOM, KiCad project" + (" · KiCad DRC" if kicad_cli() else ""))
        stats = {
            "components": len([c for c in board.components if c.footprint.style != "hole"]),
            "nets": len(board.nets), "traces": len(board.traces), "vias": len(board.vias),
            "total_trace_mm": round(sum(t.length for t in board.traces), 1),
            "routed_pct": round(100.0 * (1 - len(route_res["failed"]) / max(1, n_routable)), 1),
            "drc_errors": drc["errors"], "ripups": route_res["ripups"],
        }
        exp = await run.run_blocking(export_all, board, design_json, drc, stats, run.dir, keepouts, True)
        files = exp["files"]
        await run.emit({"type": "artifacts", "run_id": run.id, "zip_url": f"/api/runs/{run.id}/{exp['zip']}",
                        "gerber_zip_url": f"/api/runs/{run.id}/{exp['gerber_zip']}",
                        "files": files, "kicad": exp["kicad"],
                        "render_url": f"/api/runs/{run.id}/render-top.png" if exp["kicad"].get("render") else None})
        k = exp["kicad"]
        await run.status("export", "done", ("KiCad DRC " + ("PASS" if k.get("drc_passed") else f"{k.get('violations', '?')} issues")) if k.get("available") else "Package ready")
        stats["elapsed_s"] = round(time.time() - run.t0, 1)
        stats["kicad_drc_passed"] = k.get("drc_passed")
        await run.emit({"type": "done", "stats": stats})
    except Exception as e:  # noqa
        traceback.print_exc()
        await run.emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
    finally:
        run.save()
    return run


def _keepouts(board: Board):
    from .footprints import ANT_H
    from .model import rotate
    out = []
    for c in board.components:
        fp = c.footprint
        if fp.style == "module" and fp.edge == "+y":
            ax0, ay0 = rotate(-fp.body_w / 2, fp.body_h / 2 - ANT_H, c.rot)
            ax1, ay1 = rotate(fp.body_w / 2, fp.body_h / 2, c.rot)
            x0, x1 = sorted([c.x + ax0, c.x + ax1])
            y0, y1 = sorted([c.y + ay0, c.y + ay1])
            out.append((max(0, x0), max(0, y0), min(board.width, x1), min(board.height, y1)))
    return out
