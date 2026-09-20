"""Design data model shared by all pipeline stages."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .catalog import Part, CATALOG
from .footprints import Footprint, Pad


@dataclass
class Component:
    ref: str
    part: Part
    value: str = ""
    purpose: str = ""
    x: float = 0.0
    y: float = 0.0
    rot: int = 0  # degrees CCW, multiple of 90
    fixed: bool = False

    @property
    def footprint(self) -> Footprint:
        return self.part.footprint

    def pad_abs(self, pad: Pad) -> tuple[float, float, float, float]:
        """Absolute (x, y, w, h) of a pad (w/h swapped for 90/270)."""
        x, y = rotate(pad.x, pad.y, self.rot)
        w, h = (pad.w, pad.h) if self.rot % 180 == 0 else (pad.h, pad.w)
        return self.x + x, self.y + y, w, h

    def courtyard_abs(self) -> tuple[float, float, float, float]:
        cx, cy, cw, ch = self.footprint.courtyard
        corners = [rotate(cx, cy, self.rot), rotate(cx + cw, cy, self.rot), rotate(cx, cy + ch, self.rot), rotate(cx + cw, cy + ch, self.rot)]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return self.x + min(xs), self.y + min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def pad(self, num: str) -> Optional[Pad]:
        for p in self.footprint.pads:
            if p.num == num:
                return p
        return None

    def to_json(self):
        d = self.part.to_json()
        d.update({"ref": self.ref, "value": self.value, "purpose": self.purpose})
        return d


@dataclass
class Net:
    name: str
    pins: list[tuple[str, str]]  # (ref, pad_num)
    cls: str = "signal"  # gnd | power | signal | highspeed | analog
    voltage: float = 0.0
    current_ma: float = 0.0

    @property
    def width(self) -> float:
        if self.cls == "power":
            if self.current_ma >= 1500:
                return 1.0
            if self.current_ma >= 600:
                return 0.6
            return 0.4
        if self.cls == "gnd":
            return 0.4
        return 0.25

    def to_json(self):
        d = {"name": self.name, "cls": self.cls, "pins": [f"{r}.{p}" for r, p in self.pins]}
        if self.cls == "power":
            d["voltage"] = self.voltage
            d["current_ma"] = self.current_ma
        return d


@dataclass
class Trace:
    net: str
    layer: str
    width: float
    points: list[tuple[float, float]]

    @property
    def length(self) -> float:
        return sum(math.dist(self.points[i], self.points[i + 1]) for i in range(len(self.points) - 1))

    def to_json(self):
        return {"net": self.net, "layer": self.layer, "width": self.width, "points": [[round(x, 3), round(y, 3)] for x, y in self.points]}


@dataclass
class Via:
    net: str
    x: float
    y: float
    drill: float = 0.3
    diameter: float = 0.6

    def to_json(self):
        return {"net": self.net, "x": round(self.x, 3), "y": round(self.y, 3), "drill": self.drill, "diameter": self.diameter}


@dataclass
class Board:
    width: float
    height: float
    corner_radius: float = 2.0
    color: str = "black"
    mounting_holes: bool = True
    name: str = "ETCH"
    components: list[Component] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)
    traces: list[Trace] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    texts: list[dict] = field(default_factory=list)
    pour_net: str = "GND"
    pour_clearance: float = 0.3

    def comp(self, ref: str) -> Optional[Component]:
        for c in self.components:
            if c.ref == ref:
                return c
        return None

    def net_of(self, ref: str, pad: str) -> Optional[Net]:
        for n in self.nets:
            if (ref, pad) in n.pins:
                return n
        return None

    @property
    def holes(self) -> list[dict]:
        out = []
        for c in self.components:
            if c.part.category == "mechanical" and c.footprint.style == "hole":
                p = c.footprint.pads[0]
                out.append({"x": round(c.x, 3), "y": round(c.y, 3), "drill": p.drill, "diameter": p.w})
        return out

    def outline(self) -> list[tuple[float, float]]:
        r = self.corner_radius
        w, h = self.width, self.height
        pts = []
        n = 8
        for cx, cy, a0 in [(w - r, h - r, 0), (r, h - r, 90), (r, r, 180), (w - r, r, 270)]:
            for i in range(n + 1):
                a = math.radians(a0 + 90 * i / n)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    def to_json(self):
        fps = {}
        for c in self.components:
            fps[c.ref] = c.footprint.to_json()
        return {
            "width": self.width, "height": self.height, "corner_radius": self.corner_radius, "color": self.color,
            "outline": [[round(x, 3), round(y, 3)] for x, y in self.outline()],
            "holes": self.holes,
            "footprints": fps,
            "texts": self.texts,
        }


def rotate(x: float, y: float, rot: int) -> tuple[float, float]:
    rot %= 360
    if rot == 0:
        return x, y
    if rot == 90:
        return -y, x
    if rot == 180:
        return -x, -y
    return y, -x
