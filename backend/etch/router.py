"""Two-layer grid maze router (A*, 8 directions, vias) with clearance-aware obstacles and rip-up/reroute.

Layer 0 = F.Cu (components), layer 1 = B.Cu (GND pour). Signals prefer the top layer; the bottom layer is a
ground plane that gets cut only when needed. GND pins are connected to the plane with a short stub + via.
"""
from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional

import numpy as np

from .footprints import ANT_H
from .drc import RULES, Item, collect_items, distance, _pt_seg
from .model import Board, Component, Trace, Via, rotate

G = 0.2  # default grid pitch mm
FINE_G = 0.1
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
    # Each row of the disk is a horizontal interval. Grow those intervals
    # cumulatively, then shift them vertically: O(R) whole-array operations
    # instead of one for each of the O(R²) disk offsets. Integer squared
    # distances retain the original strict '< R' boundary exactly.
    limit = math.ceil(R * R) - 1
    rows = [(min(r, nx - 1, math.isqrt(limit - dy * dy)), dy)
            for dy in range(min(r, ny - 1) + 1) if dy * dy <= limit]
    horizontal = mask.copy()
    expanded = 0
    for reach, dy in sorted(rows):
        while expanded < reach:
            expanded += 1
            horizontal[:, expanded:] |= mask[:, :-expanded]
            horizontal[:, :-expanded] |= mask[:, expanded:]
        if dy:
            out[dy:] |= horizontal[:-dy]
            out[:-dy] |= horizontal[dy:]
        else:
            out |= horizontal
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
    grid_offset: float = 0.0
    cell_radii: list[float] | None = None


class Router:
    def __init__(self, board: Board, on_event: Callable[[dict], None] | None = None, time_budget: float = 240.0,
                 grid_pitch: float | None = None):
        self.b = board
        # Half-millimetre pad rows need a grid that preserves their escape lanes.
        fine_pitch = any(
            math.dist((p.x, p.y), (q.x, q.y)) <= 0.5 + 1e-6
            for c in board.components
            for i, p in enumerate(c.footprint.pads) if p.layer != "through"
            for q in c.footprint.pads[i + 1:] if q.layer != "through"
        )
        self._refine = grid_pitch is None and fine_pitch
        self.grid = grid_pitch if grid_pitch is not None else G
        if not math.isfinite(self.grid) or self.grid <= 0:
            raise ValueError("grid_pitch must be positive and finite")
        self.emit = on_event or (lambda e: None)
        self.nx = int(math.ceil(board.width / self.grid)) + 1
        self.ny = int(math.ceil(board.height / self.grid)) + 1
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
        self._connected_nets: set[int] = set()
        self._active_nets: set[int] = set()
        self.failed: list[str] = []
        self.ripups = 0
        self.pour_cells: Optional[np.ndarray] = None
        self._interior_cache: dict = {}
        self._build_static()

    # ------------------------------------------------------------------ static obstacles
    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x / self.grid)), int(round(y / self.grid))

    def _build_static(self):
        b = self.b
        ny, nx = self.ny, self.nx
        xs = np.arange(nx) * self.grid
        ys = np.arange(ny) * self.grid
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
        # no top-layer routing underneath small parts (passives, ICs, switches, LEDs, crystals): it is legal but looks
        # like traces "crossing" components and makes rework impossible. Own pads stay routable (unblocked per net).
        self.under_body = np.zeros((ny, nx), dtype=bool)
        for c in b.components:
            fp = c.footprint
            if fp.style in ("module", "connector", "usb", "header", "hole", "tht", "electrolytic") or fp.body_w * fp.body_h > 60:
                continue
            hw, hh = fp.body_w / 2 - 0.15, fp.body_h / 2 - 0.15
            if hw <= 0 or hh <= 0:
                continue
            corners = [rotate(sx * hw, sy * hh, c.rot) for sx in (-1, 1) for sy in (-1, 1)]
            x0, x1 = c.x + min(p[0] for p in corners), c.x + max(p[0] for p in corners)
            y0, y1 = c.y + min(p[1] for p in corners), c.y + max(p[1] for p in corners)
            self.under_body |= (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
        self.under_body_l = np.zeros((2, ny, nx), dtype=bool)
        self.under_body_l[0] = self.under_body
        self.owner[self.hard] = -1
        self.X, self.Y = X, Y
        self.via_drill_block = np.zeros((ny, nx), dtype=bool)
        pseudo = len(self.nets)
        for c in b.components:
            for p in c.footprint.pads:
                if p.layer == "through":
                    cx, cy, _, _ = c.pad_abs(p)
                    gap = (p.drill + VIA_DRILL) / 2 + RULES['hole_to_hole_mm']
                    self.via_drill_block |= (X - cx) ** 2 + (Y - cy) ** 2 < (gap - 1e-6) ** 2
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

    def _pad_cells(self, pr: PinRef) -> list[tuple[int, int, int]]:
        x0, y0, x1, y1 = pr.rect
        i0, i1 = int(math.ceil((x0 + 1e-6) / self.grid)), int(math.floor((x1 - 1e-6) / self.grid))
        j0, j1 = int(math.ceil((y0 + 1e-6) / self.grid)), int(math.floor((y1 - 1e-6) / self.grid))
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
            i0 = max(0, int(math.floor((x0 - e) / self.grid)))
            i1 = min(self.nx - 1, int(math.ceil((x1 + e) / self.grid)))
            j0 = max(0, int(math.floor((y0 - e) / self.grid)))
            j1 = min(self.ny - 1, int(math.ceil((y1 + e) / self.grid)))
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
        # Drill spacing applies even to vias on the same net. Reusing an
        # existing own-net via is legal; adding a second nearby hole is not.
        drill_block = dilate(self.is_via, (VIA_DRILL + RULES['hole_to_hole_mm'] - 1e-6) / self.grid)
        own_via = self.is_via & (self.owner[0] == own) & (self.owner[1] == own)
        via_hard |= self.via_drill_block | (drill_block & ~own_via)
        # escape stubs of other nets are as hard as pads
        stub_other = other & self.stub
        if stub_other.any():
            for l in range(2):
                hardb[l] |= dilate(stub_other[l], (w / 2 + CLR + 0.1) / self.grid)
            via_hard |= dilate(stub_other[0] | stub_other[1], (VIA_DIA / 2 + CLR + 0.1) / self.grid)
        trace_other = other & ~self.stub
        radii = [float(r) for r in np.unique(self.radius[trace_other])] if trace_other.any() else []
        for r_obs in radii:
            tier = trace_other & (self.radius == np.float32(r_obs))
            R = (w / 2 + CLR + r_obs) / self.grid
            for l in range(2):
                softb[l] |= dilate(tier[l], R)
            via_soft |= dilate(tier[0] | tier[1], (VIA_DIA / 2 + CLR + r_obs) / self.grid)
            # A nested reroute cannot undo the route whose conflict it is fixing.
            protected = tier & np.isin(self.owner, [n + 1 for n in self._active_nets if n != ni])
            for l in range(2):
                hardb[l] |= dilate(protected[l], R)
            via_hard |= dilate(protected[0] | protected[1], (VIA_DIA / 2 + CLR + r_obs) / self.grid)
        ownmask = self.owner == own
        hardb &= ~ownmask
        softb &= ~ownmask
        hardb |= self.no_route
        return hardb, softb, via_hard, via_soft

    # ------------------------------------------------------------------ A*
    def _astar(self, starts, target, blocked, via_ok, region, goal_bottom=False, via_cost=14.0, layer_mult=(1.0, 1.35),
               turn_pen=0.6, hweight=1.2, max_nodes=400000, soft=None, via_soft=None, soft_pen=30.0, extra=None, extra_pen=float(os.environ.get("ETCH_BODY_PEN", "1.5"))):
        nx, NL = self.nx, self.NL
        # Costs expressed as detour distances must not change when refining the
        # grid; otherwise fine routing overuses vias and congests both layers.
        via_cost *= G / self.grid
        turn_pen *= G / self.grid
        y0, y1, x0, x1 = region
        blk = blocked.ravel().tolist()
        sft = soft.ravel().tolist() if soft is not None else None
        vsft = via_soft.ravel().tolist() if via_soft is not None else None
        tgt = target.ravel().tolist() if not goal_bottom else None
        vok = via_ok.ravel().tolist()
        xtra = extra.ravel().tolist() if extra is not None else None
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
        path_vias = {}
        drill_gap2 = ((VIA_DRILL + RULES['hole_to_hole_mm'] - 1e-6) / self.grid) ** 2
        open_ = []
        for (l, y, x) in starts:
            idx = l * NL + y * nx + x
            g[idx] = 0.0
            parent[idx] = -1
            pdir[idx] = -1
            path_vias[idx] = ()
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
            if n % 1024 == 0 and self.time_left() <= 0:
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
                if xtra is not None and xtra[nidx]:
                    ng += extra_pen
                if ng < g.get(nidx, INF):
                    g[nidx] = ng
                    parent[nidx] = idx
                    pdir[nidx] = d
                    path_vias[nidx] = path_vias[idx]
                    heapq.heappush(open_, (ng + h(nxp, nyp), ng, nidx))
            vi = y * nx + x
            soft_via = vsft is not None and vsft[vi]
            # Existing holes are in via_ok; holes introduced earlier in this
            # candidate path must also obey drill spacing before commit.
            if vok[vi] and all((vx == x and vy == y) or (vx - x) ** 2 + (vy - y) ** 2 >= drill_gap2
                               for vx, vy in path_vias[idx]):
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
                        path_vias[nidx] = path_vias[idx] + ((x, y),)
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
    def _commit(self, ni: int, w: float, path, start_pt=None, end_pt=None, pin_key=None, straight=False) -> RouteRec:
        traces, vias = [], []
        net = self.nets[ni].name if ni < len(self.nets) else f"N{ni}"
        own = ni + 1
        run: list[tuple[float, float]] = []
        run_layer = path[0][0]
        first = True
        for k, (l, y, x) in enumerate(path):
            px, py = x * self.grid, y * self.grid
            if k > 0 and l != path[k - 1][0]:
                for ll in range(2):
                    o = int(self.owner[ll, y, x])
                    if o > 0 and o != own and DEBUG:
                        import traceback
                        print(f"!! via of net {net} placed on cell owned by net {o - 1} ({self.nets[o - 1].name if o - 1 < len(self.nets) else 'pseudo'}) layer {ll} at {px},{py} r={self.radius[ll, y, x]} stub={self.stub[ll, y, x]}")
                        traceback.print_stack(limit=4)
                via = next((v for v in self.b.vias + vias
                            if v.net == net and abs(v.x - px) < 1e-6 and abs(v.y - py) < 1e-6), None)
                if via is None:
                    via = Via(net, px, py, VIA_DRILL, VIA_DIA)
                if via not in vias:
                    vias.append(via)
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
        grid_offset = 0.0
        if straight:
            # The grid records occupancy, not the off-grid pad centres. Export
            # the exact centre-to-centre link rather than snapping its copper.
            traces = [Trace(net, "F.Cu" if run_layer == 0 else "B.Cu", w, [start_pt, end_pt])]
            grid_offset = max(_pt_seg(x * self.grid, y * self.grid, *start_pt, *end_pt) for l, y, x in path)
            for l, y, x in path:
                if not self.is_via[y, x]:
                    self.radius[l, y, x] = max(self.radius[l, y, x], np.float32(w / 2 + grid_offset))
        rec = RouteRec(ni, pin_key, list(path), w, traces, vias, grid_offset)
        if ni < len(self.nets) and self.nets[ni].cls == 'power':
            from .power_routing import widen_traces

            reserved = []
            for l in (0, 1):
                ys, xs = np.nonzero(self.stub[l] & (self.owner[l] > 0) & (self.owner[l] != own))
                reserved += [Item('circle', '', 'F.Cu' if l == 0 else 'B.Cu', 'escape',
                                  (x * self.grid, y * self.grid), 0.1) for y, x in zip(ys, xs)]
            traces = widen_traces(self.b, self.nets[ni], traces, reserved)
            rec.traces = traces
            rec.cell_radii = []
            for l, y, x in path:
                radius = w / 2 + grid_offset
                for tr in traces:
                    if tr.layer != ('F.Cu' if l == 0 else 'B.Cu'):
                        continue
                    for a, b in zip(tr.points, tr.points[1:]):
                        offset = _pt_seg(x * self.grid, y * self.grid, *a, *b)
                        if offset <= self.grid / math.sqrt(2) + 1e-6:
                            radius = max(radius, tr.width / 2 + offset)
                rec.cell_radii.append(radius)
                if self.owner[l, y, x] == own:
                    self.radius[l, y, x] = max(self.radius[l, y, x], np.float32(radius))
        self.routes.setdefault(ni, []).append(rec)
        for t in traces:
            self.b.traces.append(t)
            self.emit({"type": "trace", **t.to_json()})
        for v in vias:
            if v not in self.b.vias:
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
        self._connected_nets.discard(ni)
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
                if v in self.b.vias and not any(v in other.vias for other in keep):
                    self.b.vias.remove(v)
        self._mark_pads()
        for r in keep:
            for k, (l, y, x) in enumerate(r.path):
                if self.owner[l, y, x] in (0, ni + 1):
                    self.owner[l, y, x] = ni + 1
                    radius = r.cell_radii[k] if r.cell_radii is not None else r.width / 2 + r.grid_offset
                    self.radius[l, y, x] = max(self.radius[l, y, x], np.float32(radius))
            for v in r.vias:
                i, j = self._cell(v.x, v.y)
                self.is_via[j, i] = True
                for ll in range(2):
                    self.owner[ll, j, i] = ni + 1
                    self.radius[ll, j, i] = max(self.radius[ll, j, i], VIA_DIA / 2)
                    self.stub[ll, j, i] = False
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
        R = int(math.ceil((max(w / 2, VIA_DIA / 2) + CLR + float(self.radius.max())) / self.grid))
        via_cells = {(y, x) for k, (l, y, x) in enumerate(path) if k and l != path[k - 1][0]}
        samples = list(path)
        # A* also checks both orthogonal flank cells for a diagonal step. Include
        # their blockers, or a soft path can require a rip-up we never identify.
        for a, b in zip(path, path[1:]):
            if a[0] == b[0] and a[1] != b[1] and a[2] != b[2]:
                samples.extend([(a[0], a[1], b[2]), (a[0], b[1], a[2])])
        for l, y, x in samples:
            y0, y1 = max(0, y - R), min(self.ny, y + R + 1)
            x0, x1 = max(0, x - R), min(self.nx, x + R + 1)
            is_via = (y, x) in via_cells
            for ll in (range(2) if is_via else (l,)):
                sub = self.owner[ll, y0:y1, x0:x1]
                rad = self.radius[ll, y0:y1, x0:x1]
                stb = self.stub[ll, y0:y1, x0:x1]
                yy, xx = np.ogrid[y0:y1, x0:x1]
                gap = (VIA_DIA / 2 if is_via else w / 2) + CLR + rad
                near = ((xx - x) * self.grid) ** 2 + ((yy - y) * self.grid) ** 2 < gap ** 2
                for v in np.unique(sub[(sub > 0) & (rad > 0) & ~stb & near]):
                    crossed.add(int(v) - 1)
        return {c for c in crossed if c < len(self.nets) and c not in self._active_nets}

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

    def _path_clear(self, ni, w, path):
        """Validate a proposed soft path against the post-rip-up hard rules."""
        hard, soft, via_hard, via_soft = self._blocked_for(ni, w)
        blocked = hard | soft
        for a, b in zip(path, path[1:]):
            l, y, x = b
            if blocked[l, y, x]:
                return False
            if a[0] != l:
                if via_hard[y, x] or via_soft[y, x]:
                    return False
            elif a[1] != y and a[2] != x and blocked[l, a[1], x] and blocked[l, y, a[2]]:
                return False
        return True

    def route_net(self, ni: int, allow_ripup=True) -> bool:
        # Nested repairs may finish a net before its turn in the main queue.
        # Do not route it twice, or reuse stale partial copper after a failure.
        if ni in self._connected_nets:
            return True
        self.ripup(ni)
        self._active_nets.add(ni)
        self.failed = [n for n in self.failed if n != self.nets[ni].name]
        try:
            ok = self._route_net(ni, allow_ripup and len(self._active_nets) <= 3)
            if ok:
                self._connected_nets.add(ni)
            return ok
        finally:
            self._active_nets.remove(ni)

    def _route_net(self, ni: int, allow_ripup=True) -> bool:
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
            bpts = np.stack([bxs * self.grid, bys * self.grid], axis=1)

            def dist_to_blob(p):
                cx, cy = p.center
                return float(np.min(np.hypot(bpts[:, 0] - cx, bpts[:, 1] - cy)))

            pin = min(remaining, key=dist_to_blob)
            remaining.remove(pin)
            w = net.width
            for cp in connected + [pin]:
                w = min(w, _pin_w(cp))
            w = round(max(0.2, w), 2)
            direct = self._direct_pad_link(ni, pin, connected, w)
            path = direct[0] if direct else self._route_pin_to_blob(ni, pin, blob, w)
            if path is None and w > 0.25:
                w = 0.25
                path = self._route_pin_to_blob(ni, pin, blob, w)
            if path is None and allow_ripup and self.time_left() > 20:
                path = self._route_pin_to_blob(ni, pin, blob, w, soft=True)
                if path is not None:
                    for cn in sorted(self._crossed_nets(path, w) - {ni}):
                        self.ripup(cn)
                        to_reroute.append(cn)
                    if not self._path_clear(ni, w, path):
                        path = self._route_pin_to_blob(ni, pin, blob, w)
            if path is None:
                ok_all = False
                self.failed.append(net.name)
                self.emit({"type": "route_fail", "net": net.name, "reason": f"no path for {pin.comp.ref}.{pin.pad.num}"})
                for l, y, x in self.pad_cells[pin.key]:
                    blob[l, y, x] = True
                connected.append(pin)
                continue
            end_pt = direct[1] if direct else self._pad_center_at(ni, path[-1])
            self._commit(ni, w, path, start_pt=pin.center, end_pt=end_pt, straight=direct is not None)
            for l, y, x in path:
                blob[l, y, x] = True
                if self.is_via[y, x]:
                    blob[0, y, x] = blob[1, y, x] = True
            for l, y, x in self.pad_cells[pin.key]:
                blob[l, y, x] = True
            connected.append(pin)
        for cn in dict.fromkeys(to_reroute):
            if self.nets[cn].cls == "gnd":
                self._route_all_gnd_stubs(allow_ripup=False)
            else:
                self.route_net(cn, allow_ripup=allow_ripup)
        return ok_all

    def _pad_center_at(self, ni: int, cell):
        for key, cells in self.pad_cells.items():
            pr = self.pins[key]
            if pr.net_idx == ni and (cell in cells or cell in self._interior_cache[key]):
                return pr.center
        # A direct pad link need not lie on the routing grid. Branches must
        # meet its actual centreline, not merely the rounded occupancy cell.
        l, y, x = cell
        point = (x * self.grid, y * self.grid)
        for rec in self.routes.get(ni, []):
            if not rec.grid_offset or cell not in rec.path:
                continue
            for tr in rec.traces:
                if tr.layer != ("F.Cu" if l == 0 else "B.Cu"):
                    continue
                for a, b in zip(tr.points, tr.points[1:]):
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    length2 = dx * dx + dy * dy
                    t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2)) if length2 else 0
                    projection = (a[0] + t * dx, a[1] + t * dy)
                    if math.dist(point, projection) <= self.grid / math.sqrt(2) + 1e-6:
                        return projection
        return None

    def _direct_pad_link(self, ni: int, pin: PinRef, connected: list[PinRef], w: float):
        """Join aligned same-footprint pads without looping past their escapes.

        Normal fine-pitch fan-out still uses A*. These short links are allowed
        only when exact copper geometry and reserved neighbouring escapes are
        clear, and do not create vias or change the track/clearance rules.
        """
        a = pin.center
        targets = [p.center for p in connected if p.comp is pin.comp
                   and (abs(a[0] - p.center[0]) < 1e-6 or abs(a[1] - p.center[1]) < 1e-6)]
        for b in sorted(targets, key=lambda p: math.dist(a, p)):
            if math.dist(a, b) < 1e-6:
                continue
            copper = Item('seg', self.nets[ni].name, 'F.Cu', 'pad link', (*a, *b), w / 2)
            if any(it.layer == copper.layer and it.net != copper.net and distance(copper, it) < CLR - 1e-6
                   for it in collect_items(self.b)):
                continue
            steps = max(1, int(math.ceil(math.dist(a, b) / (self.grid / 2))))
            path = []
            for k in range(steps + 1):
                x, y = self._cell(a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps)
                cell = (0, y, x)
                if not path or path[-1] != cell:
                    path.append(cell)
            if any(not (0 <= y < self.ny and 0 <= x < self.nx) or self.hard[l, y, x]
                   for l, y, x in path):
                continue
            # Future escapes are reserved copper even before their net routes.
            ys, xs = np.nonzero(self.stub[0] & (self.owner[0] != ni + 1))
            if any(distance(copper, Item('circle', '', 'F.Cu', '', (x * self.grid, y * self.grid), 0.1)) < CLR - 1e-6
                   for y, x in zip(ys, xs)):
                continue
            return path, b
        return None

    def _route_pin_to_blob(self, ni: int, pin: PinRef, blob: np.ndarray, w: float, soft=False):
        hardb, softb, via_hard, via_soft = self._blocked_for(ni, w)
        starts = self.pad_cells[pin.key]
        target = blob.copy()
        pad_block = self._pad_block_for(CLR + w / 2)
        # A connected pad can be entered directly, not only through its fixed
        # escape. Otherwise a branch doubles back along the pad's edge and can
        # leave a narrow copper neck between that dogleg and the pad.
        for key, cells in self.pad_cells.items():
            pr = self.pins[key]
            if key == pin.key or pr.net_idx != ni or not any(blob[cell] for cell in cells):
                continue
            for cell in self._interior_cache[key]:
                if self.hard[cell] or pad_block[cell] not in (0, ni + 1):
                    continue
                target[cell] = True
                hardb[cell] = False
        # Near a connected via, terminate at the drill centre rather than an
        # adjacent escape cell whose final pad stub can graze the annulus.
        for via in self.b.vias:
            if via.net != self.nets[ni].name:
                continue
            x, y = self._cell(via.x, via.y)
            if not blob[:, y, x].any():
                continue
            near = (self.X - via.x) ** 2 + (self.Y - via.y) ** 2 <= (via.diameter / 2 + w / 2 + self.grid) ** 2
            target[:, near] = False
            target[:, y, x] = True
        for l, y, x in starts:
            target[l, y, x] = False
            hardb[l, y, x] = False
        extra = self.under_body_l
        if self.nets[ni].cls == 'power' and w < self.nets[ni].width:
            wide_hard, wide_soft, _, _ = self._blocked_for(ni, self.nets[ni].width)
            # Prefer a corridor that can carry the current-class width. A
            # narrow fallback remains connected, but is explicitly audited.
            extra = extra | wide_hard | wide_soft
        if soft:
            region = self._region(starts, target, 10000)
            return self._astar(starts, target, hardb, ~via_hard, region, soft=softb, via_soft=via_soft, max_nodes=600000, extra=extra)
        blocked = hardb | softb
        via_ok = ~(via_hard | via_soft)
        if self.nets[ni].cls == 'power' and w < self.nets[ni].width:
            from .power_routing import _pads, NECK_REACH, WIDTH_STEP

            # Search for a full-width trunk first. The half-cell diagonal
            # allowance protects the copper between adjacent grid centres.
            trunk_width = self.nets[ni].width + math.sqrt(2) * self.grid
            wide_hard, wide_soft, _, _ = self._blocked_for(ni, trunk_width)
            # Own occupancy is not permission for wider copper to touch a
            # neighbouring pad when leaving or joining an existing branch.
            wide_pads = self._pad_block_for(CLR + trunk_width / 2)
            wide_hard |= (wide_pads != 0) & (wide_pads != ni + 1)
            neck = np.zeros_like(blocked)
            neck_reach = max(0, NECK_REACH - WIDTH_STEP - self.grid / math.sqrt(2))
            for (x0, y0, x1, y1), layer, _ in _pads(self.b, self.nets[ni]):
                dx = np.maximum(np.maximum(x0 - self.X, self.X - x1), 0)
                dy = np.maximum(np.maximum(y0 - self.Y, self.Y - y1), 0)
                near = dx * dx + dy * dy <= neck_reach ** 2
                neck[0] |= near
                if layer == 'through':
                    neck[1] |= near
            wide_blocked = blocked | ((wide_hard | wide_soft) & ~neck)
            wide_starts = [cell for cell in starts if not wide_blocked[cell]]
            for margin in (int(math.ceil(10 / self.grid)), 10000):
                if not wide_starts:
                    break
                region = self._region(starts, target, margin)
                path = self._astar(wide_starts, target, wide_blocked, via_ok, region, extra=self.under_body_l, max_nodes=100000)
                if path is not None:
                    return path
                if self.time_left() < 5:
                    break
        for margin in (int(math.ceil(10 / self.grid)), 10000):
            region = self._region(starts, target, margin)
            path = self._astar(starts, target, blocked, via_ok, region, extra=extra)
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
        for margin in (int(math.ceil(mm / self.grid)) for mm in (3, 9, 24)):
            region = self._region(starts, None, margin)
            path = self._astar(starts, target, blocked, via_ok, region, goal_bottom=goal_bottom, via_cost=2.0, extra=self.under_body_l)
            if path is not None:
                break
        to_reroute = []
        if path is None and allow_ripup:
            region = self._region(starts, None, int(math.ceil(9 / self.grid)))
            path = self._astar(starts, target, hardb, ~via_hard, region, goal_bottom=goal_bottom, via_cost=2.0, soft=softb, via_soft=via_soft)
            if path is not None:
                for cn in sorted(self._crossed_nets(path, w) - {ni}):
                    self.ripup(cn)
                    to_reroute.append(cn)
                if not self._path_clear(ni, w, path):
                    path = None
        if path is None:
            # fallback: join existing GND copper on the top layer (another pad's stub / via) instead of dropping a new via
            # Reserved pad escapes are not copper. Only join paths which were
            # actually committed, otherwise two unconnected pads can form a
            # floating GND branch that the grid mistakes for a plane connection.
            blob = np.zeros_like(self.owner, dtype=bool)
            for rec in self.routes.get(ni, []):
                for l, y, x in rec.path:
                    blob[l, y, x] = True
            for l, y, x in starts:
                blob[l, y, x] = False
            if blob.any():
                path = self._route_pin_to_blob(ni, pin, blob, w, soft=False)
            if path is None:
                self.emit({"type": "route_fail", "net": self.nets[ni].name, "reason": f"no via spot near {pin.comp.ref}.{pin.pad.num}"})
                self.failed.append(self.nets[ni].name)
        if path is not None:
            self._commit(ni, w, path, start_pt=pin.center, pin_key=pin.key)
        for cn in to_reroute:
            if self.nets[cn].cls == "gnd":
                self._route_all_gnd_stubs(allow_ripup=False)
            else:
                self.route_net(cn, allow_ripup=False)
        return path is not None

    def _route_all_gnd_stubs(self, allow_ripup=True):
        gn = self.nets[self.gnd_idx]
        self.failed = [n for n in self.failed if n != gn.name]
        pins = [self.pins[k] for k in gn.pins if k in self.pins]
        pins.sort(key=lambda p: p.min_dim)  # fine-pitch pins first: least freedom
        for p in pins:
            self.route_gnd_stub(p, allow_ripup=allow_ripup)

    def time_left(self) -> float:
        return self.time_budget - (time.time() - self.t0)

    # ------------------------------------------------------------------ pour analysis
    def pour_mask(self) -> np.ndarray:
        """Conservative pour core, excluding necks removed by zone filling."""
        gnd = self.gnd_idx
        own = (gnd + 1) if gnd is not None else -99
        other = (self.owner[1] > 0) & (self.owner[1] != own)
        m = ~self.hard[1] & ~other
        clearance = self.b.pour_clearance + self.b.pour_min_thickness / 2
        for r_obs in np.unique(self.radius[1][other]) if other.any() else []:
            tier = other & (self.radius[1] == r_obs)
            m &= ~dilate(tier, (clearance + float(r_obs)) / self.grid)
        pb = self._pad_block_for(clearance)
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
        # Separate pour polygons can be electrically connected by a top-layer
        # GND jumper. Count connectivity, not just the 2-D flood-fill islands.
        # Otherwise healing adds working bridges but reports *more* orphans
        # (the new bridge vias), triggering needless rerouting.
        parent = list(range(cur + 1))

        def root(label):
            while parent[label] != label:
                parent[label] = parent[parent[label]]
                label = parent[label]
            return label

        through_cells = {(y, x) for key, pr in self.pins.items()
                         if pr.net_idx == self.gnd_idx and 1 in pr.layers
                         for _, y, x in self.pad_cells[key]}
        for rec in self.routes.get(self.gnd_idx, []):
            touched = {int(labels[y, x]) for l, y, x in rec.path
                       if labels[y, x] and (l == 1 or self.is_via[y, x] or (y, x) in through_cells)}
            if touched:
                first = root(min(touched))
                for label in touched:
                    parent[root(label)] = first
        merged = np.array([root(label) for label in range(cur + 1)], dtype=np.int32)
        labels = merged[labels]
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
        gnd = self.gnd_idx
        # End on actual GND copper, not an arbitrary flood-fill cell: the grid
        # pour estimate can differ from KiCad's thermal/zone geometry.
        anchors = [(v.x, v.y) for v in self.b.vias if v.net == self.nets[gnd].name]
        anchors += [p.center for p in self.pins.values() if p.net_idx == gnd and 1 in p.layers]
        for ax, ay in anchors:
            i, j = self._cell(ax, ay)
            if labels[j, i] == main:
                target[:, j, i] = True
        for ax, ay in orphans:
            i, j = self._cell(ax, ay)
            # Orphan anchors are existing vias or through-hole pads, so both
            # layers are already connected without placing a new via-in-pad.
            starts = [(0, j, i), (1, j, i)]
            region = self._region(starts, target, 60)
            path = None
            for width in (0.3, 0.2):
                # Fine-pitch ground stubs can leave a 0.2 mm escape corridor.
                # A wider repair must not make an already legal escape unusable.
                hardb, softb, via_hard, via_soft = self._blocked_for(gnd, width)
                path = self._astar(starts, target, hardb | softb, ~(via_hard | via_soft),
                                   region, layer_mult=(1.6, 1.0))
                if path is not None:
                    break
            if path is None:
                continue
            self._commit(gnd, width, path)
            healed += 1
        return healed

    # ------------------------------------------------------------------ driver
    def route_all(self) -> dict:
        """Keep the fast coarse solution; refine incomplete or width-limited boards.

        Both passes share one time budget. Refinement is transactional: a worse
        candidate cannot replace the board or leave stale copper in the UI.
        An explicit grid_pitch disables automatic refinement for diagnostics.
        """
        if not self._refine:
            return self._route_all()
        emit, events = self.emit, []
        budget, started = self.time_budget, self.t0

        def record(event):
            events.append(event)
            emit(event)

        self.emit = record
        self.time_budget = min(60.0, budget / 3)
        try:
            result = self._route_all()
        finally:
            self.emit, self.time_budget = emit, budget
        from .power_routing import width_summary

        def power_limits(board):
            return [width_summary(board, n) for n in board.nets if n.cls == 'power' and len(n.pins) >= 2]

        if (not result['failed'] and not result['orphan_gnd']
                and all(p['width_ok'] for p in power_limits(self.b))) or self.time_left() < 10:
            return result

        from .drc import run_drc

        def score(board, res):
            drc = run_drc(board, res['failed'], res['orphan_gnd'])
            power = power_limits(board)
            power_warnings = sum(not p['width_ok'] for p in power)
            return (drc['errors'], len(res['failed']), res['orphan_gnd'], drc['warnings'] - power_warnings,
                    power_warnings, sum(p['constrained_mm'] for p in power))

        baseline = score(self.b, result)
        board = self.b
        candidate = Router(replace(board, traces=[], vias=[]), emit,
                           time_budget=self.time_left(), grid_pitch=FINE_G)
        emit({'type': 'reset_routing', 'reason': 'refining fine-pitch escapes to 0.1 mm'})
        refined = candidate.route_all()
        if score(candidate.b, refined) < baseline:
            board.traces, board.vias = candidate.b.traces, candidate.b.vias
            self.__dict__.update(candidate.__dict__)
            self.b, self.t0, self.time_budget = board, started, budget
            return refined
        emit({'type': 'reset_routing', 'reason': 'keeping the better routing result'})
        for event in events:
            emit(event)
        return result

    def _route_all(self) -> dict:
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
        # Allocate power trunks before movable signal and ground vias consume
        # their escape corridors. Other nets' pad stubs remain hard obstacles.
        for _, _, i in sorted((o for o in order if self.nets[o[2]].cls == 'power'),
                              key=lambda o: (-self.nets[o[2]].width, o[1])):
            if self.time_left() < 3:
                self.failed.append(self.nets[i].name)
                self.emit({"type": "route_fail", "net": self.nets[i].name, "reason": "time budget exhausted"})
                continue
            self.route_net(i)
            routed += 1
            self._progress(routed, total)
        order = [o for o in order if self.nets[o[2]].cls != 'power']
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
            # Other GND pads can join a stub instead of owning their own via.
            # Moving that stub silently disconnects those branches; keep it and
            # bridge its island to the main pour instead.
            healed = self.heal_islands(labels, main, orphans)
            labels, main, orphans = self.pour_islands()
        self.emit({"type": "pour", "layer": "B.Cu", "net": self.nets[self.gnd_idx].name if self.gnd_idx is not None else "GND",
                   "clearance": b.pour_clearance, "islands_healed": healed, "orphans": len(orphans)})
        failed = sorted(set(self.failed))
        routed = total - len(failed)
        if orphans and self.gnd_idx is not None and self.nets[self.gnd_idx].name not in failed:
            routed -= 1
        self._progress(routed, total)
        return {"routed": routed, "total": total, "failed": failed, "orphan_gnd": len(orphans), "grid_mm": self.grid,
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
