"""Simulated-annealing component placement with edge-constrained connectors.

Streams intermediate frames via a callback so the frontend can animate the parts settling.
"""
from __future__ import annotations

import math
import random
from typing import Callable

from .model import Board, Component, rotate

EDGES = ("bottom", "top", "left", "right")
NET_WEIGHT = {"signal": 1.0, "highspeed": 1.4, "analog": 1.1, "power": 0.55, "gnd": 0.25}


def _edge_pose(board: Board, c: Component, edge: str, t: float) -> tuple[float, float, int]:
    """Pose for an edge-constrained part. `t` in [0,1] along the edge. footprint.edge is the local side that must touch the edge."""
    side = c.footprint.edge or "-y"
    # rotation that maps local `side` direction onto the outward normal of `edge`
    rot_map = {
        "-y": {"bottom": 0, "top": 180, "left": 270, "right": 90},
        "+y": {"bottom": 180, "top": 0, "left": 90, "right": 270},
    }[side]
    rot = rot_map[edge]
    cx, cy, cw, ch = c.footprint.courtyard
    bw, bh = c.footprint.body_w, c.footprint.body_h
    # local extents after rotation
    corners = [rotate(-bw / 2, -bh / 2, rot), rotate(bw / 2, -bh / 2, rot), rotate(-bw / 2, bh / 2, rot), rotate(bw / 2, bh / 2, rot)]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    ccorners = [rotate(cx, cy, rot), rotate(cx + cw, cy, rot), rotate(cx, cy + ch, rot), rotate(cx + cw, cy + ch, rot)]
    cxs = [p[0] for p in ccorners]
    cys = [p[1] for p in ccorners]
    m = 7.0 if board.mounting_holes else 2.5  # keep away from corners / mounting holes
    x_lo, x_hi = m - min(cxs), board.width - m - max(cxs)
    y_lo, y_hi = m - min(cys), board.height - m - max(cys)
    if x_hi < x_lo:
        x_lo = x_hi = board.width / 2
    if y_hi < y_lo:
        y_lo = y_hi = board.height / 2
    if edge == "bottom":
        return x_lo + (x_hi - x_lo) * t, -min(ys), rot
    if edge == "top":
        return x_lo + (x_hi - x_lo) * t, board.height - max(ys), rot
    if edge == "left":
        return -min(xs), y_lo + (y_hi - y_lo) * t, rot
    return board.width - max(xs), y_lo + (y_hi - y_lo) * t, rot


def size_board(board: Board, proposed_w: float, proposed_h: float) -> tuple[float, float]:
    """Make sure the board is big enough for the parts (with routing room)."""
    area = 0.0
    max_w = max_h = 0.0
    for c in board.components:
        cx, cy, cw, ch = c.footprint.courtyard
        area += cw * ch
        max_w = max(max_w, cw)
        max_h = max(max_h, ch)
    need = area * 3.1 + 180
    w, h = proposed_w, proposed_h
    if w * h < need:
        k = math.sqrt(need / (w * h))
        w, h = w * k, h * k
    w = max(w, max_w + 8, max_h + 8, 25)
    h = max(h, min(max_w, max_h) + 8, 20)
    return round(w / 2) * 2.0, round(h / 2) * 2.0


class Placer:
    def __init__(self, board: Board, seed: int = 7):
        self.b = board
        self.rng = random.Random(seed)
        self.comps = [c for c in board.components if not c.fixed]
        self.edge_state: dict[str, tuple[str, float]] = {}
        # net -> list of (component, pad)
        self.net_pads: list[list[tuple[Component, object]]] = []
        self.net_w: list[float] = []
        self.comp_nets: dict[str, list[int]] = {c.ref: [] for c in board.components}
        for n in board.nets:
            pads = []
            for ref, pnum in n.pins:
                c = board.comp(ref)
                if not c:
                    continue
                p = c.pad(pnum)
                if p is None:
                    continue
                pads.append((c, p))
            if len(pads) < 2:
                continue
            idx = len(self.net_pads)
            self.net_pads.append(pads)
            self.net_w.append(NET_WEIGHT.get(n.cls, 1.0))
            for c, _ in pads:
                if idx not in self.comp_nets[c.ref]:
                    self.comp_nets[c.ref].append(idx)
        # connectivity graph for the "affinity" term (passives hug their IC)
        self.affinity: dict[str, dict[str, float]] = {c.ref: {} for c in board.components}
        for pads, w in zip(self.net_pads, self.net_w):
            if w < 0.5:
                continue
            refs = sorted({c.ref for c, _ in pads})
            if len(refs) > 6:
                continue
            for a in refs:
                for b in refs:
                    if a != b:
                        self.affinity[a][b] = self.affinity[a].get(b, 0) + 1.0

    # ---------------------------------------------------------------- cost pieces
    def _net_cost(self, i: int) -> float:
        pads = self.net_pads[i]
        xs, ys = [], []
        for c, p in pads:
            x, y = rotate(p.x, p.y, c.rot)
            xs.append(c.x + x)
            ys.append(c.y + y)
        return (max(xs) - min(xs) + max(ys) - min(ys)) * self.net_w[i]

    GAP = 0.9  # desired free space between courtyards (mm) — routing room

    def _overlap_cost(self, c: Component) -> float:
        ax, ay, aw, ah = c.courtyard_abs()
        g = self.GAP / 2
        cost = 0.0
        for o in self.b.components:
            if o is c:
                continue
            bx, by, bw, bh = o.courtyard_abs()
            ix = min(ax + aw, bx + bw) - max(ax, bx)
            iy = min(ay + ah, by + bh) - max(ay, by)
            if ix > 0 and iy > 0:
                cost += 40.0 * ix * iy + 25.0
            # soft repulsion: inflated courtyards
            jx = min(ax + aw + g, bx + bw + g) - max(ax - g, bx - g)
            jy = min(ay + ah + g, by + bh + g) - max(ay - g, by - g)
            if jx > 0 and jy > 0:
                cost += 6.0 * jx * jy + 3.0
        # out of bounds
        m = 0.6
        ox = max(0.0, m - ax) + max(0.0, ax + aw - (self.b.width - m))
        oy = max(0.0, m - ay) + max(0.0, ay + ah - (self.b.height - m))
        if ox or oy:
            cost += 60.0 * (ox * ah + oy * aw) + 40.0
        return cost

    def _comp_cost(self, c: Component) -> float:
        return sum(self._net_cost(i) for i in self.comp_nets[c.ref]) + self._overlap_cost(c)

    def total_cost(self) -> float:
        cost = sum(self._net_cost(i) for i in range(len(self.net_pads)))
        for c in self.b.components:
            cost += self._overlap_cost(c) / 2.0  # pair counted twice
        return cost

    # ---------------------------------------------------------------- init
    def init_positions(self):
        b = self.b
        edge_comps = [c for c in self.comps if c.footprint.edge]
        free = [c for c in self.comps if not c.footprint.edge]
        # connectors along the bottom, then spread others around remaining edges
        order = sorted(edge_comps, key=lambda c: (0 if c.part.category == "connector" else 1, c.ref))
        slots = []
        n_bottom = min(len(order), max(1, math.ceil(len(order) * 0.5)))
        for i in range(n_bottom):
            slots.append(("bottom", (i + 1) / (n_bottom + 1)))
        rest = order[n_bottom:]
        cyc = ["top", "left", "right"]
        for i, c in enumerate(rest):
            slots.append((cyc[i % 3], self.rng.uniform(0.25, 0.75)))
        for c, (e, t) in zip(order, slots):
            if c.footprint.edge == "+y":  # antenna modules like the top edge
                e = "top"
            self.edge_state[c.ref] = (e, t)
            c.x, c.y, c.rot = _edge_pose(b, c, e, t)
        # MCU in the centre, others around
        free.sort(key=lambda c: -c.footprint.body_w * c.footprint.body_h)
        for i, c in enumerate(free):
            if i == 0:
                c.x, c.y = b.width * 0.5, b.height * 0.5
            else:
                c.x = self.rng.uniform(4, b.width - 4)
                c.y = self.rng.uniform(4, b.height - 4)
            c.rot = self.rng.choice([0, 90, 180, 270]) if c.footprint.body_w < 8 else 0

    # ---------------------------------------------------------------- moves
    def _propose(self, c: Component, T: float, scale: float):
        """Mutate c in place; return undo tuple."""
        undo = (c.x, c.y, c.rot, self.edge_state.get(c.ref))
        if c.footprint.edge:
            e, t = self.edge_state[c.ref]
            r = self.rng.random()
            if r < 0.15 and c.footprint.edge != "+y":
                e = self.rng.choice(EDGES)
            else:
                t = min(1.0, max(0.0, t + self.rng.gauss(0, 0.08 + 0.3 * scale)))
            self.edge_state[c.ref] = (e, t)
            c.x, c.y, c.rot = _edge_pose(self.b, c, e, t)
            return undo
        r = self.rng.random()
        if r < 0.72:
            s = 0.6 + scale * max(self.b.width, self.b.height) * 0.35
            c.x += self.rng.gauss(0, s)
            c.y += self.rng.gauss(0, s)
            cx, cy, cw, ch = c.footprint.courtyard
            c.x = min(max(c.x, -cx + 0.6), self.b.width - (cx + cw) - 0.6)
            c.y = min(max(c.y, -cy + 0.6), self.b.height - (cy + ch) - 0.6)
        elif r < 0.9:
            c.rot = (c.rot + self.rng.choice([90, 180, 270])) % 360
        else:
            # jump next to an affine neighbour (decoupling cap hugging its IC)
            nb = self.affinity.get(c.ref)
            if nb:
                other = self.b.comp(self.rng.choice(list(nb.keys())))
                if other is not None:
                    ox, oy, ow, oh = other.courtyard_abs()
                    ang = self.rng.uniform(0, 2 * math.pi)
                    rad = max(ow, oh) / 2 + max(c.footprint.body_w, c.footprint.body_h) / 2 + 0.6
                    c.x = ox + ow / 2 + rad * math.cos(ang)
                    c.y = oy + oh / 2 + rad * math.sin(ang)
        return undo

    def _undo(self, c: Component, undo):
        c.x, c.y, c.rot, es = undo
        if es is not None:
            self.edge_state[c.ref] = es

    # ---------------------------------------------------------------- run
    def run(self, on_frame: Callable[[int, int, float, float], None] | None = None, frames: int = 60, iterations: int | None = None):
        self.init_positions()
        n = len(self.comps)
        if n == 0:
            return
        total = iterations or min(30000, 1500 + 420 * n)
        # calibrate T0
        deltas = []
        for _ in range(60):
            c = self.rng.choice(self.comps)
            before = self._comp_cost(c)
            u = self._propose(c, 1.0, 1.0)
            deltas.append(abs(self._comp_cost(c) - before))
            self._undo(c, u)
        T0 = max(1.0, sum(deltas) / len(deltas)) * 1.5
        T_end = T0 * 5e-4
        cost = self.total_cost()
        best = cost
        best_pos = {c.ref: (c.x, c.y, c.rot) for c in self.comps}
        frame_every = max(1, total // frames)
        for it in range(total):
            frac = it / total
            T = T0 * (T_end / T0) ** frac
            c = self.rng.choice(self.comps)
            before = self._comp_cost(c)
            undo = self._propose(c, T, 1.0 - frac)
            after = self._comp_cost(c)
            d = after - before
            if d <= 0 or self.rng.random() < math.exp(-d / T):
                cost += d
                if cost < best:
                    best = cost
                    best_pos = {cc.ref: (cc.x, cc.y, cc.rot) for cc in self.comps}
            else:
                self._undo(c, undo)
            if on_frame and it % frame_every == 0:
                on_frame(it, total, T, cost)
        # restore best
        for c in self.comps:
            c.x, c.y, c.rot = best_pos[c.ref]
        for c in self.comps:
            if not c.footprint.edge:
                c.x = round(c.x * 4) / 4
                c.y = round(c.y * 4) / 4
        self.legalize()
        if on_frame:
            on_frame(total, total, 0.0, self.total_cost())

    def legalize(self, passes: int = 60):
        """Push overlapping courtyards apart."""
        comps = [c for c in self.comps if not c.footprint.edge]
        for _ in range(passes):
            moved = False
            for c in comps:
                ax, ay, aw, ah = c.courtyard_abs()
                for o in self.b.components:
                    if o is c:
                        continue
                    bx, by, bw, bh = o.courtyard_abs()
                    ix = min(ax + aw, bx + bw) - max(ax, bx)
                    iy = min(ay + ah, by + bh) - max(ay, by)
                    if ix > 0.01 and iy > 0.01:
                        moved = True
                        if ix < iy:
                            c.x += (ix + 0.2) * (1 if ax + aw / 2 >= bx + bw / 2 else -1)
                        else:
                            c.y += (iy + 0.2) * (1 if ay + ah / 2 >= by + bh / 2 else -1)
                        ax, ay, aw, ah = c.courtyard_abs()
                cx, cy, cw, ch = c.footprint.courtyard
                c.x = min(max(c.x, -cx + 0.6), self.b.width - (cx + cw) - 0.6)
                c.y = min(max(c.y, -cy + 0.6), self.b.height - (cy + ch) - 0.6)
            if not moved:
                break


def ratsnest(board: Board) -> list[list]:
    """MST airwires per net: [x1,y1,x2,y2,net]."""
    lines = []
    for n in board.nets:
        pts = []
        for ref, pnum in n.pins:
            c = board.comp(ref)
            p = c.pad(pnum) if c else None
            if p is None:
                continue
            x, y = rotate(p.x, p.y, c.rot)
            pts.append((c.x + x, c.y + y))
        if len(pts) < 2:
            continue
        in_tree = [0]
        rest = list(range(1, len(pts)))
        while rest:
            best = None
            for i in in_tree:
                for j in rest:
                    d = math.dist(pts[i], pts[j])
                    if best is None or d < best[0]:
                        best = (d, i, j)
            _, i, j = best
            lines.append([round(pts[i][0], 2), round(pts[i][1], 2), round(pts[j][0], 2), round(pts[j][1], 2), n.name])
            in_tree.append(j)
            rest.remove(j)
    return lines
