"""Replay a run's design and verify every committed route against the live blocked map. Usage: -m tests.check_commits <run_id> <seed>"""
import sys, traceback
import numpy as np
from etch import agent
from etch.placement import Placer
from etch.router import Router, G
from etch.drc import run_drc

rid, seed = sys.argv[1], int(sys.argv[2])
text = open(f"runs/{rid}/agent_output.md").read()
b, design = agent.build_board(agent._extract_json(text), "black", [])
Placer(b, seed=seed).run()
ev = []; r = Router(b, on_event=ev.append)
orig_commit = r._commit
def checked_commit(ni, w, path, start_pt=None, end_pt=None, pin_key=None):
    hardb, softb, via_hard, via_soft = r._blocked_for(ni, w)
    blk = hardb | softb
    bad = [(l, y, x) for (l, y, x) in path if blk[l, y, x]]
    vias_bad = [(y, x) for k, (l, y, x) in enumerate(path) if k > 0 and l != path[k - 1][0] and (via_hard[y, x] or via_soft[y, x])]
    if bad or vias_bad:
        name = r.nets[ni].name if ni < len(r.nets) else ni
        print(f"!! commit {name} w={w} pin={pin_key}: {len(bad)} blocked cells {bad[:3]}, blocked vias {vias_bad[:3]}")
        for (y, x) in vias_bad[:1]:
            sub = r.owner[:, y-4:y+5, x-4:x+5]
            print("   owners near via F:\n", sub[0], "\n   B:\n", sub[1], "\n   stub F:\n", r.stub[0, y-4:y+5, x-4:x+5].astype(int))
        print("   stack:", " <- ".join(f.name for f in traceback.extract_stack()[-5:-1]))
    return orig_commit(ni, w, path, start_pt=start_pt, end_pt=end_pt, pin_key=pin_key)
r._commit = checked_commit
res = r.route_all()
print(res)
drc = run_drc(b, res["failed"], res["orphan_gnd"])
print("DRC", drc["passed"], drc["errors"], [v["message"] for v in drc["violations"][:4]])
