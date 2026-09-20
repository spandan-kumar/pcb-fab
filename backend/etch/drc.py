"""Design rule check against JLCPCB 2-layer capabilities, using exact geometry (not the routing grid)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Board, rotate

RULES = {
    "fab": "JLCPCB 2-layer, 1 oz Cu",
    "min_trace_mm": 0.127,
    "min_clearance_mm": 0.127,
    "min_drill_mm": 0.3,
    "min_annular_mm": 0.13,
    "min_via_diameter_mm": 0.5,
    "edge_clearance_mm": 0.3,
    "hole_to_copper_mm": 0.254,
    "design_clearance_mm": 0.18,
}


@dataclass
class Item:
    kind: str  # seg | rect | circle
    net: str
    layer: str  # F.Cu | B.Cu
    ref: str
    a: tuple  # seg: (x1,y1,x2,y2) ; rect: (x0,y0,x1,y1) ; circle: (cx,cy)
    r: float  # half width / radius (0 for rect)

    @property
    def bbox(self):
        if self.kind == "seg":
            x1, y1, x2, y2 = self.a
            return min(x1, x2) - self.r, min(y1, y2) - self.r, max(x1, x2) + self.r, max(y1, y2) + self.r
        if self.kind == "rect":
            return self.a
        cx, cy = self.a
        return cx - self.r, cy - self.r, cx + self.r, cy + self.r


def _pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _seg_seg(a, b):
    x1, y1, x2, y2 = a
    x3, y3, x4, y4 = b
    # intersection test
    d1 = (x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)
    d2 = (x4 - x3) * (y2 - y3) - (y4 - y3) * (x2 - x3)
    d3 = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
    d4 = (x2 - x1) * (y4 - y1) - (y2 - y1) * (x4 - x1)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return 0.0
    return min(_pt_seg(x1, y1, *b), _pt_seg(x2, y2, *b), _pt_seg(x3, y3, *a), _pt_seg(x4, y4, *a))


def _pt_rect(px, py, x0, y0, x1, y1):
    dx = max(x0 - px, 0, px - x1)
    dy = max(y0 - py, 0, py - y1)
    return math.hypot(dx, dy)


def _seg_rect(seg, rect):
    x0, y0, x1, y1 = rect
    sx1, sy1, sx2, sy2 = seg
    if x0 <= sx1 <= x1 and y0 <= sy1 <= y1:
        return 0.0
    if x0 <= sx2 <= x1 and y0 <= sy2 <= y1:
        return 0.0
    edges = [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]
    return min(_seg_seg(seg, e) for e in edges)


def _rect_rect(a, b):
    dx = max(a[0] - b[2], 0, b[0] - a[2])
    dy = max(a[1] - b[3], 0, b[1] - a[3])
    return math.hypot(dx, dy)


def distance(p: Item, q: Item) -> float:
    """Copper-to-copper gap between two items."""
    if p.kind == "seg" and q.kind == "seg":
        return _seg_seg(p.a, q.a) - p.r - q.r
    if p.kind == "circle" and q.kind == "circle":
        return math.hypot(p.a[0] - q.a[0], p.a[1] - q.a[1]) - p.r - q.r
    if p.kind == "rect" and q.kind == "rect":
        return _rect_rect(p.a, q.a)
    if p.kind == "seg" and q.kind == "circle":
        return _pt_seg(q.a[0], q.a[1], *p.a) - p.r - q.r
    if p.kind == "circle" and q.kind == "seg":
        return distance(q, p)
    if p.kind == "seg" and q.kind == "rect":
        return _seg_rect(p.a, q.a) - p.r
    if p.kind == "rect" and q.kind == "seg":
        return distance(q, p)
    if p.kind == "circle" and q.kind == "rect":
        return _pt_rect(p.a[0], p.a[1], *q.a) - p.r
    return distance(q, p)


def collect_items(board: Board) -> list[Item]:
    items = []
    for c in board.components:
        for pad in c.footprint.pads:
            if pad.layer == "through" and not pad.plated:
                continue
            cx, cy, w, h = c.pad_abs(pad)
            net = board.net_of(c.ref, pad.num)
            nn = net.name if net else f"__nc_{c.ref}.{pad.num}"
            layers = ["F.Cu", "B.Cu"] if pad.layer == "through" else ["F.Cu"]
            for L in layers:
                if pad.shape == "circle":
                    items.append(Item("circle", nn, L, f"{c.ref}.{pad.num}", (cx, cy), w / 2))
                else:
                    items.append(Item("rect", nn, L, f"{c.ref}.{pad.num}", (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 0.0))
    for t in board.traces:
        for i in range(len(t.points) - 1):
            x1, y1 = t.points[i]
            x2, y2 = t.points[i + 1]
            items.append(Item("seg", t.net, t.layer, t.net, (x1, y1, x2, y2), t.width / 2))
    for v in board.vias:
        for L in ("F.Cu", "B.Cu"):
            items.append(Item("circle", v.net, L, f"via:{v.net}", (v.x, v.y), v.diameter / 2))
    return items


def run_drc(board: Board, routing_failed: list[str] | None = None, orphan_gnd: int = 0) -> dict:
    items = collect_items(board)
    violations = []
    # spatial hash
    cell = 2.0
    grid: dict[tuple, list[int]] = {}
    for idx, it in enumerate(items):
        x0, y0, x1, y1 = it.bbox
        for gx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
            for gy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                grid.setdefault((it.layer, gx, gy), []).append(idx)
    checked = set()
    n_pairs = 0
    min_clr = RULES["min_clearance_mm"]
    for key, idxs in grid.items():
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                a, b = idxs[i], idxs[j]
                if a > b:
                    a, b = b, a
                if (a, b) in checked:
                    continue
                checked.add((a, b))
                p, q = items[a], items[b]
                if p.net == q.net:
                    continue
                n_pairs += 1
                d = distance(p, q)
                if d < min_clr:
                    bx = (p.bbox[0] + p.bbox[2] + q.bbox[0] + q.bbox[2]) / 4
                    by = (p.bbox[1] + p.bbox[3] + q.bbox[1] + q.bbox[3]) / 4
                    violations.append({"code": "clearance", "severity": "error", "layer": p.layer, "x": round(bx, 2), "y": round(by, 2),
                                       "message": f"{p.ref} ({p.net}) to {q.ref} ({q.net}): {max(d, 0):.3f} mm < {min_clr} mm"})
    # trace widths
    n_traces = 0
    for t in board.traces:
        n_traces += 1
        if t.width < RULES["min_trace_mm"]:
            violations.append({"code": "trace_width", "severity": "error", "layer": t.layer, "x": t.points[0][0], "y": t.points[0][1],
                               "message": f"Trace {t.net} width {t.width} mm < {RULES['min_trace_mm']} mm"})
    # vias / holes
    n_holes = 0
    for v in board.vias:
        n_holes += 1
        if v.drill < RULES["min_drill_mm"]:
            violations.append({"code": "drill", "severity": "error", "layer": "F.Cu", "x": v.x, "y": v.y, "message": f"Via drill {v.drill} mm < {RULES['min_drill_mm']} mm"})
        if (v.diameter - v.drill) / 2 < RULES["min_annular_mm"]:
            violations.append({"code": "annular", "severity": "error", "layer": "F.Cu", "x": v.x, "y": v.y, "message": f"Via annular ring too small"})
    for c in board.components:
        for pad in c.footprint.pads:
            if pad.layer != "through":
                continue
            n_holes += 1
            cx, cy, w, h = c.pad_abs(pad)
            if pad.plated and (min(w, h) - pad.drill) / 2 < RULES["min_annular_mm"]:
                violations.append({"code": "annular", "severity": "error", "layer": "F.Cu", "x": cx, "y": cy, "message": f"{c.ref}.{pad.num} annular ring < {RULES['min_annular_mm']} mm"})
    # edge clearance
    W, H = board.width, board.height
    ec = RULES["edge_clearance_mm"]
    n_edge = 0
    for it in items:
        n_edge += 1
        x0, y0, x1, y1 = it.bbox
        if x0 < ec or y0 < ec or x1 > W - ec or y1 > H - ec:
            # connectors are allowed to sit at the edge (their pads are inside; bodies overhang)
            violations.append({"code": "edge_clearance", "severity": "warning", "layer": it.layer, "x": round((x0 + x1) / 2, 2), "y": round((y0 + y1) / 2, 2),
                               "message": f"{it.ref} within {ec} mm of board edge"})
    # courtyard overlap
    n_court = 0
    comps = board.components
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            a, b = comps[i], comps[j]
            ax, ay, aw, ah = a.courtyard_abs()
            bx, by, bw, bh = b.courtyard_abs()
            n_court += 1
            ix = min(ax + aw, bx + bw) - max(ax, bx)
            iy = min(ay + ah, by + bh) - max(ay, by)
            if ix > 0.05 and iy > 0.05:
                violations.append({"code": "courtyard", "severity": "warning", "layer": "F.Cu", "x": round(max(ax, bx) + ix / 2, 2), "y": round(max(ay, by) + iy / 2, 2),
                                   "message": f"Courtyards of {a.ref} and {b.ref} overlap ({ix:.1f}×{iy:.1f} mm)"})
    # connectivity
    n_nets = len([n for n in board.nets if len(n.pins) >= 2])
    for name in sorted(set(routing_failed or [])):
        violations.append({"code": "unconnected", "severity": "error", "layer": "F.Cu", "x": 0, "y": 0, "message": f"Net {name} is not fully routed"})
    if orphan_gnd:
        violations.append({"code": "plane_island", "severity": "error", "layer": "B.Cu", "x": 0, "y": 0, "message": f"{orphan_gnd} GND via(s) on an isolated plane island"})
    errors = [v for v in violations if v["severity"] == "error"]
    checks = [
        {"name": "Copper clearance", "count": n_pairs, "ok": not any(v["code"] == "clearance" for v in violations)},
        {"name": "Trace width", "count": n_traces, "ok": not any(v["code"] == "trace_width" for v in violations)},
        {"name": "Drill & annular ring", "count": n_holes, "ok": not any(v["code"] in ("drill", "annular") for v in violations)},
        {"name": "Board edge clearance", "count": n_edge, "ok": not any(v["code"] == "edge_clearance" for v in violations)},
        {"name": "Courtyard overlap", "count": n_court, "ok": not any(v["code"] == "courtyard" for v in violations)},
        {"name": "Connectivity", "count": n_nets, "ok": not any(v["code"] in ("unconnected", "plane_island") for v in violations)},
    ]
    return {"passed": len(errors) == 0, "rules": RULES, "violations": violations[:200], "checks": checks,
            "errors": len(errors), "warnings": len(violations) - len(errors)}
