"""RS-274X Gerber (X2 attributes) and Excellon drill writers. Coordinates: mm, board origin bottom-left, y up."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .model import Board, rotate
from .strokefont import text_strokes

FMT = "%FSLAX46Y46*%"


def _c(v: float) -> str:
    return str(int(round(v * 1e6)))


class GerberFile:
    def __init__(self, function: str, polarity: str = "Positive", name: str = ""):
        self.function = function
        self.polarity = polarity
        self.name = name
        self.apertures: dict[str, int] = {}
        self.body: list[str] = []
        self.next_d = 10
        self.cur = None

    def aperture(self, shape: str, *dims) -> int:
        key = f"{shape}," + "X".join(f"{d:.4f}" for d in dims)
        if key not in self.apertures:
            self.apertures[key] = self.next_d
            self.next_d += 1
        return self.apertures[key]

    def _use(self, d: int):
        if self.cur != d:
            self.body.append(f"D{d}*")
            self.cur = d

    def flash(self, d: int, x: float, y: float):
        self._use(d)
        self.body.append(f"X{_c(x)}Y{_c(y)}D03*")

    def line(self, d: int, pts, closed=False):
        self._use(d)
        self.body.append(f"X{_c(pts[0][0])}Y{_c(pts[0][1])}D02*")
        for x, y in pts[1:]:
            self.body.append(f"X{_c(x)}Y{_c(y)}D01*")
        if closed:
            self.body.append(f"X{_c(pts[0][0])}Y{_c(pts[0][1])}D01*")

    def region(self, pts):
        self.body.append("G36*")
        self.body.append(f"X{_c(pts[0][0])}Y{_c(pts[0][1])}D02*")
        for x, y in pts[1:]:
            self.body.append(f"X{_c(x)}Y{_c(y)}D01*")
        self.body.append(f"X{_c(pts[0][0])}Y{_c(pts[0][1])}D01*")
        self.body.append("G37*")

    def polarity_clear(self):
        self.body.append("%LPC*%")

    def polarity_dark(self):
        self.body.append("%LPD*%")

    def render(self) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
        head = [
            "%TF.GenerationSoftware,ETCH,etch-agent,0.1*%",
            f"%TF.CreationDate,{now}*%",
            f"%TF.ProjectId,{self.name[:30] or 'etch'},45544348-2d50-4342-2d45-544348000000,rev1*%",
            "%TF.SameCoordinates,Original*%",
            f"%TF.FileFunction,{self.function}*%",
            f"%TF.FilePolarity,{self.polarity}*%",
            FMT,
            "G04 Gerber Fmt 4.6, Leading zero omitted, Abs format (unit mm)*",
            f"G04 Created by ETCH agent — {self.name}*",
            "%MOMM*%",
            "%LPD*%",
            "G01*",
            "G75*",
        ]
        aps = []
        for key, d in self.apertures.items():
            shape, dims = key.split(",", 1)
            aps.append(f"%ADD{d}{shape},{dims}*%")
        return "\n".join(head + aps + self.body + ["M02*"]) + "\n"


def _pad_aperture(g: GerberFile, pad, rot: int, grow: float = 0.0):
    w, h = (pad.w, pad.h) if rot % 180 == 0 else (pad.h, pad.w)
    w, h = w + 2 * grow, h + 2 * grow
    if pad.shape == "circle":
        return g.aperture("C", w)
    if pad.shape == "oval":
        return g.aperture("O", w, h)
    return g.aperture("R", w, h)


def _outline_pts(board: Board, inset: float = 0.0):
    r = max(0.01, board.corner_radius - inset)
    w, h = board.width - inset, board.height - inset
    x0 = y0 = inset
    pts = []
    n = 12
    for cx, cy, a0 in [(w - r, h - r, 0), (x0 + r, h - r, 90), (x0 + r, y0 + r, 180), (w - r, y0 + r, 270)]:
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def write_gerbers(board: Board, keepouts: list[tuple[float, float, float, float]] | None = None) -> dict[str, str]:
    """Returns {filename: content} for the full fabrication set."""
    name = board.name.replace(" ", "_")
    files: dict[str, str] = {}
    gnd = board.pour_net
    clr = board.pour_clearance

    # ---------------- copper
    for layer, fn, ext, func in (("F.Cu", "F_Cu", "gtl", "Copper,L1,Top"), ("B.Cu", "B_Cu", "gbl", "Copper,L2,Bot")):
        g = GerberFile(func, name=name)
        if layer == "B.Cu":
            # GND pour: positive plane, then clear around everything that is not GND, then redraw copper
            g.body.append("%TA.AperFunction,Conductor*%")
            g.region(_outline_pts(board, inset=0.4))
            g.polarity_clear()
            for h in board.holes:
                g.flash(g.aperture("C", h["diameter"] + 2 * clr), h["x"], h["y"])
            for t in board.traces:
                if t.layer == "B.Cu" and t.net != gnd:
                    g.line(g.aperture("C", t.width + 2 * clr), t.points)
            for v in board.vias:
                if v.net != gnd:
                    g.flash(g.aperture("C", v.diameter + 2 * clr), v.x, v.y)
            for c in board.components:
                for pad in c.footprint.pads:
                    if pad.layer != "through":
                        continue
                    net = board.net_of(c.ref, pad.num)
                    if net and net.name == gnd and pad.plated:
                        continue
                    cx, cy, _, _ = c.pad_abs(pad)
                    g.flash(_pad_aperture(g, pad, c.rot, grow=clr), cx, cy)
            for (x0, y0, x1, y1) in keepouts or []:
                g.region([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
            g.polarity_dark()
        for c in board.components:
            for pad in c.footprint.pads:
                if pad.layer == "through" and not pad.plated:
                    continue
                if layer == "B.Cu" and pad.layer != "through":
                    continue
                cx, cy, _, _ = c.pad_abs(pad)
                g.flash(_pad_aperture(g, pad, c.rot), cx, cy)
        for t in board.traces:
            if t.layer == layer:
                g.line(g.aperture("C", t.width), t.points)
        for v in board.vias:
            g.flash(g.aperture("C", v.diameter), v.x, v.y)
        files[f"{name}-{fn}.{ext}"] = g.render()

    # ---------------- solder mask (negative: draw openings)
    for layer, fn, ext, func in (("F", "F_Mask", "gts", "Soldermask,Top"), ("B", "B_Mask", "gbs", "Soldermask,Bot")):
        g = GerberFile(func, polarity="Negative", name=name)
        for c in board.components:
            for pad in c.footprint.pads:
                if layer == "B" and pad.layer != "through":
                    continue
                cx, cy, _, _ = c.pad_abs(pad)
                g.flash(_pad_aperture(g, pad, c.rot, grow=0.05), cx, cy)
        files[f"{name}-{fn}.{ext}"] = g.render()

    # ---------------- paste
    g = GerberFile("Paste,Top", name=name)
    for c in board.components:
        for pad in c.footprint.pads:
            if pad.layer == "F.Cu" and c.footprint.style != "hole":
                cx, cy, _, _ = c.pad_abs(pad)
                g.flash(_pad_aperture(g, pad, c.rot), cx, cy)
    files[f"{name}-F_Paste.gtp"] = g.render()

    # ---------------- silkscreen
    g = GerberFile("Legend,Top", name=name)
    d_line = g.aperture("C", 0.15)
    d_text = g.aperture("C", 0.12)
    for c in board.components:
        fp = c.footprint
        if fp.style == "hole":
            continue
        for (x1, y1, x2, y2) in fp.silk:
            ax, ay = rotate(x1, y1, c.rot)
            bx, by = rotate(x2, y2, c.rot)
            g.line(d_line, [(c.x + ax, c.y + ay), (c.x + bx, c.y + by)])
        # reference designator just outside the courtyard
        cx, cy, cw, ch = c.courtyard_abs()
        ty = cy + ch + 0.6
        if ty > board.height - 1.0:
            ty = cy - 0.6
        for stroke in text_strokes(c.ref, cx + cw / 2, ty, 0.7):
            g.line(d_text, stroke)
    for t in board.texts:
        for stroke in text_strokes(t["text"], t["x"], t["y"], t.get("size", 1.0), t.get("rot", 0)):
            g.line(g.aperture("C", max(0.12, t.get("size", 1.0) * 0.14)), stroke)
    files[f"{name}-F_SilkS.gto"] = g.render()

    g = GerberFile("Legend,Bot", name=name)
    for stroke in text_strokes(f"{board.name} - ETCH", board.width / 2, 2.0, 0.9, mirror=True):
        g.line(g.aperture("C", 0.13), stroke)
    files[f"{name}-B_SilkS.gbo"] = g.render()

    # ---------------- edge cuts
    g = GerberFile("Profile,NP", name=name)
    g.line(g.aperture("C", 0.1), _outline_pts(board), closed=True)
    files[f"{name}-Edge_Cuts.gm1"] = g.render()

    # ---------------- drills
    files[f"{name}-PTH.drl"] = _excellon(board, plated=True)
    files[f"{name}-NPTH.drl"] = _excellon(board, plated=False)
    return files


def _excellon(board: Board, plated: bool) -> str:
    holes: dict[float, list[tuple[float, float]]] = {}
    if plated:
        for v in board.vias:
            holes.setdefault(round(v.drill, 3), []).append((v.x, v.y))
    for c in board.components:
        for pad in c.footprint.pads:
            if pad.layer != "through" or pad.plated != plated:
                continue
            cx, cy, _, _ = c.pad_abs(pad)
            holes.setdefault(round(pad.drill, 3), []).append((cx, cy))
    lines = ["M48", "; DRILL file {ETCH} date " + datetime.now().strftime("%Y-%m-%d"),
             f"; FORMAT={{-:-/ absolute / metric / decimal}}", f"; #@! TF.FileFunction,{'Plated' if plated else 'NonPlated'},1,2,{'PTH' if plated else 'NPTH'}",
             "FMAT,2", "METRIC"]
    tools = sorted(holes)
    for i, d in enumerate(tools):
        lines.append(f"T{i + 1}C{d:.3f}")
    lines += ["%", "G90", "G05"]
    for i, d in enumerate(tools):
        lines.append(f"T{i + 1}")
        for x, y in holes[d]:
            lines.append(f"X{x:.3f}Y{y:.3f}")
    lines.append("M30")
    return "\n".join(lines) + "\n"
