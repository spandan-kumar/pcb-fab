"""Rebuild a stored run's board from its agent output and re-run place/route/DRC. Usage: uv run python -m tests.replay_run <run_id> [seed]"""
import sys, json, time
from etch import agent
from etch.placement import Placer
from etch.router import Router
from etch.drc import run_drc
from tests.render import render

rid = sys.argv[1]; seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
text = open(f"runs/{rid}/agent_output.md").read()
spec = agent._extract_json(text)
b, design = agent.build_board(spec, "black", [])
Placer(b, seed=seed).run()
t = time.time(); ev = []; r = Router(b, on_event=ev.append); res = r.route_all()
print("route %.1fs" % (time.time() - t), res)
drc = run_drc(b, res["failed"], res["orphan_gnd"])
print("DRC", drc["passed"], drc["errors"], drc["warnings"])
for v in drc["violations"][:12]:
    print("  ", v["severity"], v["code"], v["message"], v["x"], v["y"])
render(b, f"/tmp/etch_{rid}_{seed}.png")
