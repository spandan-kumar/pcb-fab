"""Two-layer grid maze router (A*, 8 directions, vias) with clearance-aware obstacles and rip-up/reroute.

Layer 0 = F.Cu (components), layer 1 = B.Cu (GND pour). Signals prefer the top layer; the bottom layer is a
ground plane that gets cut only when needed. GND pins are connected to the plane with a short stub + via.
"""
from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .footprints import ANT_H
from .model import Board, Component, Trace, Via, rotate

G = 0.2  # grid pitch mm
CLR = 0.18  # routing clearance mm (JLCPCB min 0.127)
EDGE_CLR = 0.5
VIA_DIA, VIA_DRILL = 0.6, 0.3
INF = float("inf")
import os
DEBUG = bool(os.environ.get("ETCH_ROUTER_DEBUG"))

DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]


def dilate(mask: np.ndarray, R: float) -> np.ndarray:
    """Cells within Euclidean distance < R (cells) of any true cell."""
    if not mask.any():
        return np.zeros_like(mask)
    r = int(math.ceil(R))
    out = np.zeros_like(mask)
    ny, nx = mask.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy >= R * R:
                continue
            ys0, ys1 = max(0, dy), min(ny, ny + dy)
            xs0, xs1 = max(0, dx), min(nx, nx + dx)
            out[ys0:ys1, xs0:xs1] |= mask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


@dataclass
class PinRef:
    comp: Component
    pad: object
    net_idx: int

    @property
    def center(self) -> tuple[float, float]:
        x, y = rotate(self.pad.x, self.pad.y, self.comp.rot)
        return self.comp.x + x, self.comp.y + y

    @property
    def rect(self) -> tuple[float, float, float, float]:
        cx, cy, w, h = self.comp.pad_abs(self.pad)
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    @property
    def layers(self) -> tuple[int, ...]:
        return (0, 1) if self.pad.layer == "through" else (0,)

    @property
    def min_dim(self) -> float:
        return min(self.pad.w, self.pad.h)

    @property
    def key(self):
        return (self.comp.ref, self.pad.num)


@dataclass
class RouteRec:
    net_idx: int
    pin_key: Optional[tuple]  # for GND stubs
    path: list[tuple[int, int, int]]
    width: float
    traces: list[Trace]
    vias: list[Via]


class Router:
    def __init__(self, board: Board, on_event: Callable[[dict], None] | None = None, time_budget: float = 240.0):
        self.b = board
        self.emit = on_event or (lambda e: None)
        self.nx = int(math.ceil(board.width / G)) + 1
        self.ny = int(math.ceil(board.height / G)) + 1
        self.NL = self.ny * self.nx
        self.owner = np.zeros((2, self.ny, self.nx), dtype=np.int32)  # 0 free, -1 hard, k = net idx+1
        self.radius = np.zeros((2, self.ny, self.nx), dtype=np.float32)  # half-width of copper at cell (0 for pads)
        self.is_via = np.zeros((self.ny, self.nx), dtype=bool)
        self.stub = np.zeros((2, self.ny, self.nx), dtype=bool)  # fixed escape stubs of fine-pitch pads
        self.hard = np.zeros((2, self.ny, self.nx), dtype=bool)
        self.time_budget = time_budget
        self.t0 = time.time()
        self.nets = board.nets
        self.gnd_idx = next((i for i, n in enumerate(board.nets) if n.cls == "gnd"), None)
        self.pins: dict[tuple[str, str], PinRef] = {}
        self.pad_cells: dict[tuple[str, str], list[tuple[int, int, int]]] = {}  # routing start/target cells
        self.pin_marked: dict[tuple[str, str], list[tuple[int, int, int]]] = {}  # all cells owned because of the pin
        self.routes: dict[int, list[RouteRec]] = {}
        self.failed: list[str] = []
        self.ripups = 0
        self.pour_cells: Optional[np.ndarray] = None
        self._build_static()

    # ------------------------------------------------------------------ static obstacles
    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x / G)), int(round(y / G))

    def _build_static(self):
        b = self.b
        ny, nx = self.ny, self.nx
        xs = np.arange(nx) * G
        ys = np.arange(ny) * G
        X, Y = np.meshgrid(xs, ys)
        edge = (X < EDGE_CLR) | (X > b.width - EDGE_CLR) | (Y < EDGE_CLR) | (Y > b.height - EDGE_CLR)
        r = b.corner_radius + EDGE_CLR
        for cx, cy in [(r, r), (b.width - r, r), (r, b.height - r), (b.width - r, b.height - r)]:
            inside_corner_box = (np.abs(X - cx) <= r) & (np.abs(Y - cy) <= r)
            far = ((X - cx) ** 2 + (Y - cy) ** 2) > (b.corner_radius) ** 2
            corner_out = inside_corner_box & far & ((X - cx) * (cx - b.width / 2) > 0) & ((Y - cy) * (cy - b.height / 2) > 0)
            edge |= corner_out
        self.hard[0] |= edge
        self.hard[1] |= edge
        for h in b.holes:
            m = (X - h["x"]) ** 2 + (Y - h["y"]) ** 2 <= (h["diameter"] / 2 + CLR + 0.1) ** 2
            self.hard[0] |= m
            self.hard[1] |= m
        self.keepout = np.zeros((ny, nx), dtype=bool)
        for c in b.components:
            fp = c.footprint
            if fp.style == "module" and fp.edge == "+y":
                ax0, ay0 = rotate(-fp.body_w / 2, fp.body_h / 2 - ANT_H, c.rot)
                ax1, ay1 = rotate(fp.body_w / 2, fp.body_h / 2, c.rot)
                x0, x1 = sorted([c.x + ax0, c.x + ax1])
                y0, y1 = sorted([c.y + ay0, c.y + ay1])
                m = VIA_DIA / 2 + CLR  # copper must stay fully outside the keepout
                ant = (X >= x0 - m) & (X <= x1 + m) & (Y >= y0 - m) & (Y <= y1 + m)
                self.keepout |= ant
                self.hard[0] |= ant
                self.hard[1] |= ant
        self.owner[self.hard] = -1
        self.X, self.Y = X, Y
        pseudo = len(self.nets)
        for c in b.components:
            for p in c.footprint.pads:
                if not p.plated and p.layer == "through":
                    continue  # NPTH mounting hole handled as hole
                net = b.net_of(c.ref, p.num)
                if net is None:
                    ni = pseudo
                    pseudo += 1
                else:
                    ni = b.nets.index(net)
                pr = PinRef(c, p, ni)
                self.pins[pr.key] = pr
                cells = self._pad_cells(pr)
                marked = list(cells)
                esc = self._escape(pr)
                if esc is not None:
                    cells = []
                    for ecell, seg_cells in esc:
                        marked += seg_cells + [ecell]
                        cells.append(ecell)
                self.pad_cells[pr.key] = cells
                self.pin_marked[pr.key] = marked
        self.n_ids = pseudo
        self.no_route = np.zeros((2, ny, nx), dtype=bool)  # interiors/stubs of fine-pitch pads: never route through
        for key, marked in self.pin_marked.items():
            esc_cells = set(self.pad_cells[key])
            if len(marked) > len(esc_cells):  # pad has escapes: everything else is off-limits
                for (l, y, x) in marked:
                    if (l, y, x) not in esc_cells:
                        self.no_route[l, y, x] = True
        self._mark_pads()
        self.pad_block: dict[float, np.ndarray] = {}
        self.pad_rects = [(pr.net_idx, pr.layers, *pr.rect) for pr in self.pins.values()]

    def _mark_pads(self):
        for key, cells in self.pin_marked.items():
            ni = self.pins[key].net_idx
            interior = self._interior_cache.get(key, set())
            for (l, y, x) in cells:
                if self.owner[l, y, x] == 0 or self.owner[l, y, x] == ni + 1:
                    self.owner[l, y, x] = ni + 1
                    if (l, y, x) not in interior and not self.is_via[y, x]:  # escape stub cells carry a 0.1 radius so neighbours keep clearance
                        self.radius[l, y, x] = max(self.radius[l, y, x], np.float32(0.1))
                        self.stub[l, y, x] = True

    _interior_cache: dict = {}

    def _pad_cells(self, pr: PinRef) -> list[tuple[int, int, int]]:
        x0, y0, x1, y1 = pr.rect
        i0, i1 = int(math.ceil((x0 + 1e-6) / G)), int(math.floor((x1 - 1e-6) / G))
        j0, j1 = int(math.ceil((y0 + 1e-6) / G)), int(math.floor((y1 - 1e-6) / G))
        cells = []
        for l in pr.layers:
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
                    cells.append((l, j, i))
            if not any(cl == l for cl, _, _ in cells):
                cx, cy = pr.center
                i, j = self._cell(cx, cy)
                if 0 <= i < self.nx and 0 <= j < self.ny:
                    cells.append((l, j, i))
        self._interior_cache[pr.key] = set(cells)
        return cells

    def _escape(self, pr: PinRef):
        """Fine-pitch pads get fixed escape stubs: pad centre -> straight out -> escape cell (router start/target).
        Returns list of (escape_cell, stub_cells) or None."""
        p = pr.pad
        if pr.pad.layer == "through" or min(p.w, p.h) >= 0.7:
            return None
        if abs(p.x) < 1e-6 and abs(p.y) < 1e-6 and p.escape != "both":
            return None
        if p.w >= p.h:
            d0, half = ((1.0 if p.x >= 0 else -1.0), 0.0), p.w / 2
        else:
            d0, half = (0.0, (1.0 if p.y >= 0 else -1.0)), p.h / 2
        dirs = [d0, (-d0[0], -d0[1])] if p.escape == "both" else [d0]
        cx, cy = pr.center
        out = []
        for dx, dy in dirs:
            dx, dy = rotate(dx, dy, pr.comp.rot)
            ex, ey = cx + dx * (half + 0.35), cy + dy * (half + 0.35)
            i, j = self._cell(ex, ey)
            if not (0 <= i < self.nx and 0 <= j < self.ny) or self.hard[0, j, i]:
                continue
            seg = []
            n = 4
            for k in range(1, n):
                sx, sy = cx + dx * (half + 0.35) * k / n, cy + dy * (half + 0.35) * k / n
                si, sj = self._cell(sx, sy)
                if 0 <= si < self.nx and 0 <= sj < self.ny and (sj, si) != (j, i):
                    seg.append((0, sj, si))
            out.append(((0, j, i), seg))
        return out or None

    def _pad_block_for(self, e: float) -> np.ndarray:
        """int32 (2,ny,nx): 0 free, k=net+1 within e of a pad of that net, -1 within e of two different nets."""
        key = round(e, 3)
        if key in self.pad_block:
            return self.pad_block[key]
        out = np.zeros((2, self.ny, self.nx), dtype=np.int32)
        X, Y = self.X, self.Y
        for ni, layers, x0, y0, x1, y1 in self.pad_rects:
            i0 = max(0, int(math.floor((x0 - e) / G)))
            i1 = min(self.nx - 1, int(math.ceil((x1 + e) / G)))
            j0 = max(0, int(math.floor((y0 - e) / G)))
            j1 = min(self.ny - 1, int(math.ceil((y1 + e) / G)))
            if i1 < i0 or j1 < j0:
                continue
            sx = X[j0:j1 + 1, i0:i1 + 1]
            sy = Y[j0:j1 + 1, i0:i1 + 1]
            dx = np.maximum(np.maximum(x0 - sx, sx - x1), 0)
            dy = np.maximum(np.maximum(y0 - sy, sy - y1), 0)
            m = (dx * dx + dy * dy) < e * e
            for l in layers:
                sub = out[l, j0:j1 + 1, i0:i1 + 1]
                conflict = m & (sub != 0) & (sub != ni + 1)
                sub[m & (sub == 0)] = ni + 1
                sub[conflict] = -1
        self.pad_block[key] = out
        return out

    # ------------------------------------------------------------------ dynamic blocking
    def _blocked_for(self, ni: int, w: float):
        """Returns (hard_blocked[2], soft_blocked[2], via_hard[ny,nx], via_soft[ny,nx]) for routing net ni at width w.
        Hard = board/pads/escape stubs (never crossable). Soft = other nets' traces & vias (crossable in rip-up mode)."""
        own = ni + 1
        e = CLR + w / 2
        pb = self._pad_block_for(e)
        hardb = self.hard | ((pb != 0) & (pb != own))
        other = (self.owner > 0) & (self.owner != own) & (self.radius > 0)
        softb = np.zeros_like(hardb)
        via_soft = np.zeros((self.ny, self.nx), dtype=bool)
        ev = VIA_DIA / 2 + CLR
        pbv = self._pad_block_for(ev)
        via_hard = self.hard[0] | self.hard[1] | ((pbv[0] != 0) & (pbv[0] != own)) | ((pbv[1] != 0) & (pbv[1] != own))
        pbo = self._pad_block_for(VIA_DIA / 2 + 0.05)
        via_hard |= (pbo[0] != 0) | (pbo[1] != 0)  # no via-in-pad, even own net
        # escape stubs of other nets are as hard as pads
        stub_other = other & self.stub
        if stub_other.any():
            for l in range(2):
                hardb[l] |= dilate(stub_other[l], (w / 2 + CLR + 0.1) / G)
            via_hard |= dilate(stub_other[0] | stub_other[1], (VIA_DIA / 2 + CLR + 0.1) / G)
        trace_other = other & ~self.stub
        radii = [float(r) for r in np.unique(self.radius[trace_other])] if trace_other.any() else []
        for r_obs in radii:
            tier = trace_other & (self.radius == np.float32(r_obs))
            R = (w / 2 + CLR + r_obs) / G
            for l in range(2):
                softb[l] |= dilate(tier[l], R)
            via_soft |= dilate(tier[0] | tier[1], (VIA_DIA / 2 + CLR + r_obs) / G)
        ownmask = self.owner == own
        hardb &= ~ownmask
        softb &= ~ownmask
        hardb |= self.no_route
        return hardb, softb, via_hard, via_soft

    # ------------------------------------------------------------------ A*
    def _astar(self, starts, target, blocked, via_ok, region, goal_bottom=False, via_cost=14.0, layer_mult=(1.0, 1.35),
               turn_pen=0.6, hweight=1.2, max_nodes=400000, soft=None, via_soft=None, soft_pen=30.0):
        nx, NL = self.nx, self.NL
        y0, y1, x0, x1 = region
        blk = blocked.ravel().tolist()
        sft = soft.ravel().tolist() if soft is not None else None
        vsft = via_soft.ravel().tolist() if via_soft is not None else None
        tgt = target.ravel().tolist() if not goal_bottom else None
        vok = via_ok.ravel().tolist()
        if not goal_bottom:
            tys, txs = np.nonzero(target[0] | target[1])
            if len(tys) == 0:
                return None
            tbx0, tbx1, tby0, tby1 = txs.min(), txs.max(), tys.min(), tys.max()

            def h(x, y):
                dx = 0 if tbx0 <= x <= tbx1 else min(abs(x - tbx0), abs(x - tbx1))
                dy = 0 if tby0 <= y <= tby1 else min(abs(y - tby0), abs(y - tby1))
                m, M = (dx, dy) if dx < dy else (dy, dx)
                return (M - m + m * 1.41421356) * hweight
        else:
            def h(x, y):
                return 0.0
        g, parent, pdir = {}, {}, {}
        open_ = []
        for (l, y, x) in starts:
            idx = l * NL + y * nx + x
            g[idx] = 0.0
            parent[idx] = -1
            pdir[idx] = -1
            heapq.heappush(open_, (h(x, y), 0.0, idx))
        closed = set()
        n = 0
        while open_:
            f, gc, idx = heapq.heappop(open_)
            if idx in closed:
                continue
            closed.add(idx)
            n += 1
            if n > max_nodes:
                return None
            l, rem = divmod(idx, NL)
            y, x = divmod(rem, nx)
            if goal_bottom:
                if l == 1:
                    return self._path(parent, idx)
            elif tgt[idx] and g[idx] > 0:
                return self._path(parent, idx)
            pd = pdir[idx]
            lm = layer_mult[l]
            base = l * NL
            for d, (dx, dy, cost) in enumerate(DIRS):
                nxp, nyp = x + dx, y + dy
                if nxp < x0 or nxp > x1 or nyp < y0 or nyp > y1:
                    continue
                nidx = base + nyp * nx + nxp
                if nidx in closed or blk[nidx]:
                    continue
                if dx and dy and blk[base + y * nx + nxp] and blk[base + nyp * nx + x]:
                    continue
                ng = gc + cost * lm + (turn_pen if (pd != -1 and pd != d) else 0.0)
                if sft is not None and sft[nidx]:
                    ng += soft_pen
                if ng < g.get(nidx, INF):
                    g[nidx] = ng
                    parent[nidx] = idx
                    pdir[nidx] = d
                    heapq.heappush(open_, (ng + h(nxp, nyp), ng, nidx))
            vi = y * nx + x
            soft_via = vsft is not None and not vok[vi] and vsft[vi]
            if vok[vi] or soft_via:
                ol = 1 - l
                nidx = ol * NL + vi
                if nidx not in closed and not blk[nidx]:
                    ng = gc + via_cost + (soft_pen if soft_via else 0.0)
                    if sft is not None and sft[nidx]:
                        ng += soft_pen
                    if ng < g.get(nidx, INF):
                        g[nidx] = ng
                        parent[nidx] = idx
                        pdir[nidx] = -1
                        heapq.heappush(open_, (ng + h(x, y), ng, nidx))
        return None

    def _path(self, parent, idx):
        out = []
        while idx != -1:
            l, rem = divmod(idx, self.NL)
            y, x = divmod(rem, self.nx)
            out.append((l, y, x))
            idx = parent[idx]
        out.reverse()
        return out

    # ------------------------------------------------------------------ commit / rip-up
    def _commit(self, ni: int, w: float, path, start_pt=None, end_pt=None, pin_key=None) -> RouteRec:
        traces, vias = [], []
        net = self.nets[ni].name if ni < len(self.nets) else f"N{ni}"
        own = ni + 1
        run: list[tuple[float, float]] = []
        run_layer = path[0][0]
        first = True
        for k, (l, y, x) in enumerate(path):
            px, py = x * G, y * G
            if k > 0 and l != path[k - 1][0]:
                for ll in range(2):
                    o = int(self.owner[ll, y, x])
                    if o > 0 and o != own and DEBUG:
                        import traceback
                        print(f"!! via of net {net} placed on cell owned by net {o - 1} ({self.nets[o - 1].name if o - 1 < len(self.nets) else 'pseudo'}) layer {ll} at {px},{py} r={self.radius[ll, y, x]} stub={self.stub[ll, y, x]}")
                        traceback.print_stack(limit=4)
                vias.append(Via(net, px, py, VIA_DRILL, VIA_DIA))
                self.is_via[y, x] = True
                for ll in range(2):
                    self.owner[ll, y, x] = own
                    self.radius[ll, y, x] = VIA_DIA / 2
                    self.stub[ll, y, x] = False  # a via on an escape cell is a via, not a thin stub
                if len(run) >= 2:
                    traces.append(Trace(net, "F.Cu" if run_layer == 0 else "B.Cu", w, _simplify(run)))
                run = [(px, py)]
                run_layer = l
                continue
            if first and start_pt is not None:
                run.append(start_pt)
                first = False
            run.append((px, py))
            if self.owner[l, y, x] <= 0 or self.owner[l, y, x] == own:
                self.owner[l, y, x] = own
                if not self.is_via[y, x]:
                    self.radius[l, y, x] = max(self.radius[l, y, x], np.float32(w / 2))
            elif DEBUG:
                o = int(self.owner[l, y, x])
                print(f"!! trace of {net} over cell owned by {self.nets[o - 1].name if o - 1 < len(self.nets) else 'pseudo'} layer {l} at {px},{py} stub={self.stub[l, y, x]} via={self.is_via[y, x]}")
        if end_pt is not None:
            run.append(end_pt)
        if len(run) >= 2:
            traces.append(Trace(net, "F.Cu" if run_layer == 0 else "B.Cu", w, _simplify(run)))
        rec = RouteRec(ni, pin_key, list(path), w, traces, vias)
        self.routes.setdefault(ni, []).append(rec)
        for t in traces:
            self.b.traces.append(t)
            self.emit({"type": "trace", **t.to_json()})
        for v in vias:
            self.b.vias.append(v)
            self.emit({"type": "via", **v.to_json()})
        return rec

    def ripup(self, ni: int, pin_key=None) -> list[RouteRec]:
        recs = self.routes.get(ni, [])
        keep, gone = [], []
        for r in recs:
            (gone if (pin_key is None or r.pin_key == pin_key) else keep).append(r)
        if not gone:
            return []
        self.routes[ni] = keep
        for r in gone:
            for (l, y, x) in r.path:
                if self.owner[l, y, x] == ni + 1:
                    self.owner[l, y, x] = 0
                    self.radius[l, y, x] = 0
                if self.is_via[y, x] and self.owner[0, y, x] in (0, ni + 1) and self.owner[1, y, x] in (0, ni + 1):
                    self.is_via[y, x] = False
                    for ll in range(2):
                        if self.owner[ll, y, x] == ni + 1:
                            self.owner[ll, y, x] = 0
                            self.radius[ll, y, x] = 0
            for t in r.traces:
                if t in self.b.traces:
                    self.b.traces.remove(t)
            for v in r.vias:
                if v in self.b.vias:
                    self.b.vias.remove(v)
        self._mark_pads()
        for r in keep:
            for (l, y, x) in r.path:
                if self.owner[l, y, x] == 0:
                    self.owner[l, y, x] = ni + 1
                    self.radius[l, y, x] = np.float32(r.width / 2)
            for v in r.vias:
                i, j = self._cell(v.x, v.y)
                self.is_via[j, i] = True
                for ll in range(2):
                    self.owner[ll, j, i] = ni + 1
                    self.radius[ll, j, i] = VIA_DIA / 2
        self.ripups += 1
        if DEBUG:
            for v in self.b.vias:
                i, j = self._cell(v.x, v.y)
                vn = next(k for k, n in enumerate(self.nets) if n.name == v.net)
                if self.owner[0, j, i] != vn + 1 or self.owner[1, j, i] != vn + 1 or not self.is_via[j, i]:
                    print(f"!! after ripup({self.nets[ni].name}): via {v.net} at {v.x},{v.y} lost grid marks: owners {self.owner[0, j, i]},{self.owner[1, j, i]} is_via={self.is_via[j, i]}")
        self.emit({"type": "ripup", "net": self.nets[ni].name,
                   "traces": sum(len(r.traces) for r in gone), "vias": sum(len(r.vias) for r in gone)})
        return gone

    def _crossed_nets(self, path, w: float) -> set[int]:
        """Nets whose traces/vias lie within clearance of the path (used after a soft route)."""
        crossed = set()
        R = int(math.ceil((max(w / 2, VIA_DIA / 2) + CLR + VIA_DIA / 2) / G))
        for (l, y, x) in path:
            y0, y1 = max(0, y - R), min(self.ny, y + R + 1)
            x0, x1 = max(0, x - R), min(self.nx, x + R + 1)
            for ll in range(2):
                sub = self.owner[ll, y0:y1, x0:x1]
                rad = self.radius[ll, y0:y1, x0:x1]
                stb = self.stub[ll, y0:y1, x0:x1]
                for v in np.unique(sub[(sub > 0) & (rad > 0) & ~stb]):
                    crossed.add(int(v) - 1)
        return {c for c in crossed if c < len(self.nets)}

    # ------------------------------------------------------------------ per net
    def _region(self, cells, targets, margin_cells: int):
        ys = [c[1] for c in cells]
        xs = [c[2] for c in cells]
        if targets is not None:
            tys, txs = np.nonzero(targets[0] | targets[1])
            if len(tys):
                ys += [int(tys.min()), int(tys.max())]
                xs += [int(txs.min()), int(txs.max())]
        return (max(0, min(ys) - margin_cells), min(self.ny - 1, max(ys) + margin_cells),
                max(0, min(xs) - margin_cells), min(self.nx - 1, max(xs) + margin_cells))

    def route_net(self, ni: int, allow_ripup=True) -> bool:
        net = self.nets[ni]
        pins = [self.pins[p] for p in net.pins if p in self.pins]
        if len(pins) < 2:
            return True
        self.emit({"type": "route_begin", "net": net.name, "cls": net.cls})
        blob = np.zeros((2, self.ny, self.nx), dtype=bool)
        start = min(pins, key=lambda p: (p.center[0] + p.center[1]))
        for l, y, x in self.pad_cells[start.key]:
            blob[l, y, x] = True
        connected = [start]
        remaining = [p for p in pins if p is not start]
        ok_all = True
        to_reroute: list[int] = []
        while remaining:
            bys, bxs = np.nonzero(blob[0] | blob[1])
            bpts = np.stack([bxs * G, bys * G], axis=1)

            def dist_to_blob(p):
                cx, cy = p.center
                return float(np.min(np.hypot(bpts[:, 0] - cx, bpts[:, 1] - cy)))

            pin = min(remaining, key=dist_to_blob)
            remaining.remove(pin)
            w = net.width
            for cp in connected + [pin]:
                w = min(w, _pin_w(cp))
            w = round(max(0.2, w), 2)
            path = self._route_pin_to_blob(ni, pin, blob, w)
            if path is None and w > 0.25:
                w = 0.25
                path = self._route_pin_to_blob(ni, pin, blob, w)
            if path is None and allow_ripup and self.time_left() > 20:
                path = self._route_pin_to_blob(ni, pin, blob, w, soft=True)
                if path is not None:
                    for cn in self._crossed_nets(path, w) - {ni}:
                        self.ripup(cn)
                        to_reroute.append(cn)
                    path2 = self._route_pin_to_blob(ni, pin, blob, w)
                    path = path2 if path2 is not None else path
            if path is None:
                ok_all = False
                self.failed.append(net.name)
                self.emit({"type": "route_fail", "net": net.name, "reason": f"no path for {pin.comp.ref}.{pin.pad.num}"})
                for l, y, x in self.pad_cells[pin.key]:
                    blob[l, y, x] = True
                connected.append(pin)
                continue
            end_pt = self._pad_center_at(ni, path[-1])
            self._commit(ni, w, path, start_pt=pin.center, end_pt=end_pt)
            for l, y, x in path:
                blob[l, y, x] = True
                if self.is_via[y, x]:
                    blob[0, y, x] = blob[1, y, x] = True
            for l, y, x in self.pad_cells[pin.key]:
                blob[l, y, x] = True
            connected.append(pin)
        for cn in to_reroute:
            if self.nets[cn].cls == "gnd":
                self._route_all_gnd_stubs(allow_ripup=False)
            else:
                self.route_net(cn, allow_ripup=False)
        return ok_all

    def _pad_center_at(self, ni: int, cell):
        for key, cells in self.pad_cells.items():
            pr = self.pins[key]
            if pr.net_idx == ni and cell in cells:
                return pr.center
        return None

    def _route_pin_to_blob(self, ni: int, pin: PinRef, blob: np.ndarray, w: float, soft=False):
        hardb, softb, via_hard, via_soft = self._blocked_for(ni, w)
        starts = self.pad_cells[pin.key]
        target = blob.copy()
        for l, y, x in starts:
            target[l, y, x] = False
            hardb[l, y, x] = False
        if soft:
            region = self._region(starts, target, 10000)
            return self._astar(starts, target, hardb, ~via_hard, region, soft=softb, via_soft=via_soft, max_nodes=600000)
        blocked = hardb | softb
        via_ok = ~(via_hard | via_soft)
        for margin in (50, 10000):
            region = self._region(starts, target, margin)
            path = self._astar(starts, target, blocked, via_ok, region)
            if path is not None:
                return path
            if self.time_left() < 5:
                break
        return None

    def route_gnd_stub(self, pin: PinRef, allow_ripup=True, plane_mask=None) -> bool:
        """Connect a top-side GND pad to the bottom pour with a short stub and a via.
        If plane_mask (bool[ny,nx]) is given, the via must land inside that part of the pour (island healing)."""
        ni = pin.net_idx
        if 1 in pin.layers:
            return True  # through-hole pad already reaches the pour
        if any(r.pin_key == pin.key for r in self.routes.get(ni, [])):
            return True
        w = round(max(0.2, min(self.nets[ni].width, _pin_w(pin))), 2)
        hardb, softb, via_hard, via_soft = self._blocked_for(ni, w)
        starts = self.pad_cells[pin.key]
        for l, y, x in starts:
            hardb[l, y, x] = False
        blocked = hardb | softb
        via_ok = ~(via_hard | via_soft)
        target = None
        goal_bottom = plane_mask is None
        if plane_mask is not None:
            target = np.zeros((2, self.ny, self.nx), dtype=bool)
            target[1] = plane_mask & ~blocked[1]
            blocked[1] |= ~plane_mask  # never wander around the bottom layer outside the main plane
        path = None
        for margin in (15, 45, 120):
            region = self._region(starts, None, margin)
            path = self._astar(starts, target, blocked, via_ok, region, goal_bottom=goal_bottom, via_cost=2.0)
            if path is not None:
                break
        to_reroute = []
        if path is None and allow_ripup:
            region = self._region(starts, None, 45)
            path = self._astar(starts, target, hardb, ~via_hard, region, goal_bottom=goal_bottom, via_cost=2.0, soft=softb, via_soft=via_soft)
            if path is not None:
                for cn in self._crossed_nets(path, w) - {ni}:
                    self.ripup(cn)
                    to_reroute.append(cn)
        if path is None:
            # fallback: join existing GND copper on the top layer (another pad's stub / via) instead of dropping a new via
            blob = (self.owner == ni + 1) & (self.radius > 0)
            for l, y, x in starts:
                blob[l, y, x] = False
            if blob.any():
                path = self._route_pin_to_blob(ni, pin, blob, w, soft=False)
            if path is None:
                self.emit({"type": "route_fail", "net": self.nets[ni].name, "reason": f"no via spot near {pin.comp.ref}.{pin.pad.num}"})
                self.failed.append(self.nets[ni].name)
                return False
        self._commit(ni, w, path, start_pt=pin.center, pin_key=pin.key)
        for cn in to_reroute:
            if self.nets[cn].cls == "gnd":
                self._route_all_gnd_stubs(allow_ripup=False)
            else:
                self.route_net(cn, allow_ripup=False)
        return True

    def _route_all_gnd_stubs(self, allow_ripup=True):
        gn = self.nets[self.gnd_idx]
        pins = [self.pins[k] for k in gn.pins if k in self.pins]
        pins.sort(key=lambda p: p.min_dim)  # fine-pitch pins first: least freedom
        for p in pins:
            self.route_gnd_stub(p, allow_ripup=allow_ripup)

    def time_left(self) -> float:
        return self.time_budget - (time.time() - self.t0)

    # ------------------------------------------------------------------ pour analysis
    def pour_mask(self) -> np.ndarray:
        """Bottom-layer cells that remain copper in the GND pour."""
        gnd = self.gnd_idx
        own = (gnd + 1) if gnd is not None else -99
        other = (self.owner[1] > 0) & (self.owner[1] != own)
        m = ~self.hard[1] & ~other
        for r_obs in np.unique(self.radius[1][other]) if other.any() else []:
            tier = other & (self.radius[1] == r_obs)
            m &= ~dilate(tier, (self.b.pour_clearance + float(r_obs)) / G)
        pb = self._pad_block_for(self.b.pour_clearance)
        m &= ~((pb[1] != 0) & (pb[1] != own))
        return m

    def pour_islands(self):
        m = self.pour_mask()
        ny, nx = m.shape
        labels = np.zeros((ny, nx), dtype=np.int32)
        cur = 0
        stack = []
        for j in range(ny):
            for i in range(nx):
                if m[j, i] and labels[j, i] == 0:
                    cur += 1
                    stack.append((j, i))
                    labels[j, i] = cur
                    while stack:
                        y, x = stack.pop()
                        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            yy, xx = y + dy, x + dx
                            if 0 <= yy < ny and 0 <= xx < nx and m[yy, xx] and labels[yy, xx] == 0:
                                labels[yy, xx] = cur
                                stack.append((yy, xx))
        if cur == 0:
            return labels, 0, []
        gnd_name = self.nets[self.gnd_idx].name if self.gnd_idx is not None else "GND"
        anchors = [(v.x, v.y) for v in self.b.vias if v.net == gnd_name]
        for pr in self.pins.values():
            if pr.net_idx == self.gnd_idx and 1 in pr.layers:
                anchors.append(pr.center)
        counts = {}
        anchor_labels = []
        for ax, ay in anchors:
            i, j = self._cell(ax, ay)
            lab = 0
            for rad in range(0, 5):
                for dj in range(-rad, rad + 1):
                    for di in range(-rad, rad + 1):
                        jj, ii = j + dj, i + di
                        if 0 <= jj < ny and 0 <= ii < nx and labels[jj, ii]:
                            lab = labels[jj, ii]
                            break
                    if lab:
                        break
                if lab:
                    break
            anchor_labels.append(lab)
            counts[lab] = counts.get(lab, 0) + 1
        main = max(counts.items(), key=lambda kv: (kv[0] != 0, kv[1]))[0] if counts else 0
        orphans = [a for a, lab in zip(anchors, anchor_labels) if lab != main]
        self.pour_cells = labels == main
        return labels, main, orphans

    def heal_islands(self, labels, main, orphans) -> int:
        """Route GND jumpers from orphan vias to the main pour island."""
        if self.gnd_idx is None or main == 0:
            return 0
        healed = 0
        target = np.zeros((2, self.ny, self.nx), dtype=bool)
        target[1] = labels == main
        gnd = self.gnd_idx
        for ax, ay in orphans:
            i, j = self._cell(ax, ay)
            hardb, softb, via_hard, via_soft = self._blocked_for(gnd, 0.3)
            blocked = hardb | softb
            blocked[1] &= ~(labels == main)
            starts = [(1, j, i)]
            region = self._region(starts, target, 60)
            path = self._astar(starts, target, blocked, ~(via_hard | via_soft), region, layer_mult=(1.6, 1.0))
            if path is None:
                continue
            self._commit(gnd, 0.3, path)
            healed += 1
        return healed

    # ------------------------------------------------------------------ driver
    def route_all(self) -> dict:
        b = self.b
        order = []
        for i, n in enumerate(self.nets):
            if n.cls == "gnd":
                continue
            pins = [self.pins[p] for p in n.pins if p in self.pins]
            if len(pins) < 2:
                continue
            xs = [p.center[0] for p in pins]
            ys = [p.center[1] for p in pins]
            hp = (max(xs) - min(xs)) + (max(ys) - min(ys))
            pri = {"signal": 0, "highspeed": -1, "analog": 0, "power": 1}.get(n.cls, 0)
            order.append((pri, hp, i))
        order.sort()
        total = len(order) + (1 if self.gnd_idx is not None else 0)
        routed = 0
        if self.gnd_idx is not None:
            gn = self.nets[self.gnd_idx]
            self.emit({"type": "route_begin", "net": gn.name, "cls": "gnd"})
            self._route_all_gnd_stubs()
            routed += 1
            self._progress(routed, total)
        for pri, hp, i in order:
            if self.time_left() < 3:
                self.failed.append(self.nets[i].name)
                self.emit({"type": "route_fail", "net": self.nets[i].name, "reason": "time budget exhausted"})
                continue
            self.route_net(i)
            routed += 1
            self._progress(routed, total)
        # second chances for anything that failed (board state has changed since); up to 3 passes
        for _pass in range(2):
            retry = sorted(set(self.failed))
            if not retry or self.time_left() < 10:
                break
            self.failed = []
            for name in retry:
                ni = next(i for i, n in enumerate(self.nets) if n.name == name)
                if self.nets[ni].cls == "gnd":
                    self._route_all_gnd_stubs()
                    continue
                self.ripup(ni)
                self.route_net(ni)
            if len(set(self.failed)) >= len(retry):
                break
        labels, main, orphans = self.pour_islands()
        healed = 0
        if orphans and self.gnd_idx is not None:
            # 1) move stranded GND stubs so their via lands on the main plane
            gnd = self.gnd_idx
            moved = 0
            for ax, ay in orphans:
                rec = next((r for r in self.routes.get(gnd, []) if r.pin_key and any(abs(v.x - ax) < 1e-6 and abs(v.y - ay) < 1e-6 for v in r.vias)), None)
                if rec is None:
                    continue
                self.ripup(gnd, rec.pin_key)
                if self.route_gnd_stub(self.pins[rec.pin_key], allow_ripup=False, plane_mask=(labels == main)):
                    moved += 1
                else:
                    self.route_gnd_stub(self.pins[rec.pin_key], allow_ripup=False)
            labels, main, orphans = self.pour_islands()
            healed += moved
            # 2) jumpers for anything still stranded (through-hole pads etc.)
            if orphans:
                healed += self.heal_islands(labels, main, orphans)
                labels, main, orphans = self.pour_islands()
        self.emit({"type": "pour", "layer": "B.Cu", "net": self.nets[self.gnd_idx].name if self.gnd_idx is not None else "GND",
                   "clearance": b.pour_clearance, "islands_healed": healed, "orphans": len(orphans)})
        self._progress(total, total)
        return {"routed": routed, "total": total, "failed": sorted(set(self.failed)), "orphan_gnd": len(orphans),
                "length_mm": round(sum(t.length for t in b.traces), 1), "vias": len(b.vias), "ripups": self.ripups}

    def _neighbour_nets(self, ni: int, margin: float) -> list[int]:
        """Routed nets with copper inside the (expanded) bounding box of net ni's pins."""
        pins = [self.pins[p] for p in self.nets[ni].pins if p in self.pins]
        if not pins:
            return []
        xs = [p.center[0] for p in pins]
        ys = [p.center[1] for p in pins]
        i0, j0 = self._cell(max(0.0, min(xs) - margin), max(0.0, min(ys) - margin))
        i1, j1 = self._cell(min(self.b.width, max(xs) + margin), min(self.b.height, max(ys) + margin))
        sub = self.owner[:, j0:j1 + 1, i0:i1 + 1]
        rad = self.radius[:, j0:j1 + 1, i0:i1 + 1]
        stb = self.stub[:, j0:j1 + 1, i0:i1 + 1]
        ids = np.unique(sub[(sub > 0) & (rad > 0) & ~stb])
        out = [int(v) - 1 for v in ids if 0 < int(v) - 1 + 1 <= len(self.nets) and int(v) - 1 != ni]
        out = [cn for cn in out if self.routes.get(cn)]
        # short nets first when re-routing
        def hp(cn):
            ps = [self.pins[p] for p in self.nets[cn].pins if p in self.pins]
            if not ps:
                return 0
            return (max(p.center[0] for p in ps) - min(p.center[0] for p in ps)) + (max(p.center[1] for p in ps) - min(p.center[1] for p in ps))
        return sorted(out, key=hp)

    def _progress(self, routed, total):
        self.emit({"type": "routing_progress", "routed": routed, "total": total,
                   "length_mm": round(sum(t.length for t in self.b.traces), 1), "vias": len(self.b.vias)})


def _pin_w(pin: PinRef) -> float:
    """Max trace width that may touch this pad: fine-pitch pads neck down to 0.2 mm."""
    if pin.min_dim < 0.7:
        return 0.2
    return max(0.2, min(9.0, pin.min_dim - 0.02))


def _simplify(pts):
    out = []
    for p in pts:
        if out and abs(out[-1][0] - p[0]) < 1e-6 and abs(out[-1][1] - p[1]) < 1e-6:
            continue
        out.append(p)
    if len(out) < 3:
        return out
    res = [out[0]]
    for i in range(1, len(out) - 1):
        ax, ay = res[-1]
        bx, by = out[i]
        cx, cy = out[i + 1]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        d1 = math.hypot(bx - ax, by - ay)
        d2 = math.hypot(cx - bx, cy - by)
        if d1 > 0 and d2 > 0 and abs(cross) / (d1 * d2) < 1e-3 and ((bx - ax) * (cx - bx) + (by - ay) * (cy - by)) > 0:
            continue
        res.append(out[i])
    res.append(out[-1])
    return res
