"""Parametric footprint library.

All dimensions in mm, footprint-local coordinates (origin at footprint centre, y up).
Pin numbering follows IPC / KiCad conventions (pin 1 top-left, counter-clockwise).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

ANT_H = 6.0  # antenna keep-out height (mm) at the +y end of RF modules


@dataclass
class Pad:
    num: str
    x: float
    y: float
    w: float
    h: float
    shape: str = "roundrect"  # rect | roundrect | circle | oval
    layer: str = "F.Cu"  # F.Cu | through
    drill: float = 0.0
    plated: bool = True
    escape: Optional[str] = None  # None=auto (outward), "both" = escape stubs on both ends (interleaved connector pins)

    def to_json(self):
        d = {"num": self.num, "shape": self.shape, "x": round(self.x, 4), "y": round(self.y, 4),
             "w": round(self.w, 4), "h": round(self.h, 4), "layer": self.layer}
        if self.layer == "through":
            d["drill"] = self.drill
            d["plated"] = self.plated
        return d


@dataclass
class Footprint:
    name: str
    pads: list[Pad]
    body_w: float
    body_h: float
    body_z: float
    style: str  # module | chip | sot | passive | connector | usb | header | led | switch | crystal | hole | electrolytic | tht
    courtyard_margin: float = 0.25
    silk: list[tuple[float, float, float, float]] = field(default_factory=list)
    edge: Optional[str] = None  # "-y" means the -y side of the part must sit on a board edge (connector opening)
    description: str = ""

    @property
    def courtyard(self):
        xs = [p.x - p.w / 2 for p in self.pads] + [p.x + p.w / 2 for p in self.pads] + [-self.body_w / 2, self.body_w / 2]
        ys = [p.y - p.h / 2 for p in self.pads] + [p.y + p.h / 2 for p in self.pads] + [-self.body_h / 2, self.body_h / 2]
        m = self.courtyard_margin
        x0, x1, y0, y1 = min(xs) - m, max(xs) + m, min(ys) - m, max(ys) + m
        return (x0, y0, x1 - x0, y1 - y0)

    def to_json(self):
        cx, cy, cw, ch = self.courtyard
        return {
            "name": self.name,
            "pads": [p.to_json() for p in self.pads],
            "courtyard": {"x": round(cx, 3), "y": round(cy, 3), "w": round(cw, 3), "h": round(ch, 3)},
            "body": {"x": round(-self.body_w / 2, 3), "y": round(-self.body_h / 2, 3), "w": self.body_w, "h": self.body_h,
                     "z": self.body_z, "style": self.style},
            "silk": [[round(v, 3) for v in s] for s in self.silk],
            "edge": self.edge,
        }


def _rect_silk(w, h, gap=0.0):
    x, y = w / 2 + gap, h / 2 + gap
    return [(-x, -y, x, -y), (x, -y, x, y), (x, y, -x, y), (-x, y, -x, -y)]


# ---------------------------------------------------------------- two-terminal chips
CHIP_DIMS = {
    # size: (pad_w, pad_h, pad_dx, body_w, body_h, body_z)
    "0402": (0.6, 0.6, 0.5, 1.0, 0.5, 0.35),
    "0603": (0.9, 1.0, 0.8, 1.6, 0.8, 0.45),
    "0805": (1.05, 1.35, 0.95, 2.0, 1.25, 0.6),
    "1206": (1.15, 1.8, 1.5, 3.2, 1.6, 0.7),
}


def chip(size: str, style="passive") -> Footprint:
    pw, ph, dx, bw, bh, bz = CHIP_DIMS[size]
    pads = [Pad("1", -dx, 0, pw, ph), Pad("2", dx, 0, pw, ph)]
    return Footprint(f"{size}", pads, bw, bh, bz, style, courtyard_margin=0.2)


# ---------------------------------------------------------------- SOT family
def sot23(n=3) -> Footprint:
    pw, ph = 0.6, 1.1
    y = 1.1
    if n == 3:
        pads = [Pad("1", -0.95, -y, pw, ph), Pad("2", 0.95, -y, pw, ph), Pad("3", 0, y, pw, ph)]
    elif n == 5:
        pads = [Pad("1", -0.95, -y, pw, ph), Pad("2", 0, -y, pw, ph), Pad("3", 0.95, -y, pw, ph),
                Pad("4", 0.95, y, pw, ph), Pad("5", -0.95, y, pw, ph)]
    elif n == 6:
        pads = [Pad("1", -0.95, -y, pw, ph), Pad("2", 0, -y, pw, ph), Pad("3", 0.95, -y, pw, ph),
                Pad("4", 0.95, y, pw, ph), Pad("5", 0, y, pw, ph), Pad("6", -0.95, y, pw, ph)]
    elif n == 8:  # SOT-23-8, pitch 0.65
        pads = []
        xs = [-0.975, -0.325, 0.325, 0.975]
        for i, x in enumerate(xs):
            pads.append(Pad(str(i + 1), x, -y, 0.45, ph))
        for i, x in enumerate(reversed(xs)):
            pads.append(Pad(str(i + 5), x, y, 0.45, ph))
    else:
        raise ValueError(n)
    return Footprint(f"SOT-23-{n}" if n != 3 else "SOT-23", pads, 2.9, 1.3, 1.1, "sot",
                     silk=[(-1.45, 0, 1.45, 0)] if n == 3 else [], courtyard_margin=0.6 if n >= 5 else 0.3)


def sot223() -> Footprint:
    pads = [Pad("1", -2.3, -3.15, 1.2, 2.0), Pad("2", 0, -3.15, 1.2, 2.0), Pad("3", 2.3, -3.15, 1.2, 2.0),
            Pad("4", 0, 3.15, 3.6, 2.0)]
    return Footprint("SOT-223", pads, 6.5, 3.5, 1.7, "sot", silk=_rect_silk(6.5, 3.5))


# ---------------------------------------------------------------- dual-row gull-wing (SOIC/TSSOP/SSOP)
def dual_row(name, n, pitch, pad_dx, pad_w, pad_h, body_w, body_h, body_z=1.6, style="chip") -> Footprint:
    """Pins along two long sides (left/right), pin 1 top-left, counter-clockwise."""
    half = n // 2
    pads = []
    y0 = (half - 1) / 2 * pitch
    for i in range(half):
        pads.append(Pad(str(i + 1), -pad_dx, y0 - i * pitch, pad_w, pad_h))
    for i in range(half):
        pads.append(Pad(str(half + i + 1), pad_dx, -y0 + i * pitch, pad_w, pad_h))
    silk = [(-body_w / 2, body_h / 2, body_w / 2, body_h / 2), (-body_w / 2, -body_h / 2, body_w / 2, -body_h / 2)]
    return Footprint(name, pads, body_w, body_h, body_z, style, silk=silk, courtyard_margin=0.9 if pitch < 1.0 else 0.4)


def soic(n, wide=False) -> Footprint:
    body_h = {8: 4.9, 14: 8.65, 16: 9.9, 18: 11.55, 20: 12.8, 28: 17.9}[n]
    if wide:
        return dual_row(f"SOIC-{n}W", n, 1.27, 4.7, 1.55, 0.6, 7.5, body_h, 2.65)
    return dual_row(f"SOIC-{n}", n, 1.27, 2.7, 1.55, 0.6, 3.9, body_h, 1.75)


def tssop(n) -> Footprint:
    body_h = {8: 3.0, 10: 3.0, 14: 5.0, 16: 5.0, 20: 6.5, 24: 7.8, 28: 9.7}[n]
    pitch = 0.5 if n == 10 else 0.65
    return dual_row(f"TSSOP-{n}", n, pitch, 2.875, 1.35, 0.4 if pitch == 0.5 else 0.45, 4.4, body_h, 1.2)


def ssop(n) -> Footprint:
    body_h = {16: 6.2, 20: 7.2, 24: 8.2, 28: 10.2}[n]
    return dual_row(f"SSOP-{n}", n, 0.65, 3.75, 1.5, 0.45, 5.3, body_h, 2.0)


def msop(n) -> Footprint:
    return dual_row(f"MSOP-{n}", n, 0.5, 2.45, 1.4, 0.3, 3.0, 3.0, 1.1)


# ---------------------------------------------------------------- quad packages
def quad(name, n, pitch, pad_dx, pad_len, pad_w, body, body_z, epad=0.0, style="chip") -> Footprint:
    """Quad flat package. pin 1 top-left, counter-clockwise: down the left, across the bottom, up the right, across the top."""
    per = n // 4
    y0 = (per - 1) / 2 * pitch
    pads = []
    k = 1
    for i in range(per):  # left, top->bottom
        pads.append(Pad(str(k), -pad_dx, y0 - i * pitch, pad_len, pad_w)); k += 1
    for i in range(per):  # bottom, left->right
        pads.append(Pad(str(k), -y0 + i * pitch, -pad_dx, pad_w, pad_len)); k += 1
    for i in range(per):  # right, bottom->top
        pads.append(Pad(str(k), pad_dx, -y0 + i * pitch, pad_len, pad_w)); k += 1
    for i in range(per):  # top, right->left
        pads.append(Pad(str(k), y0 - i * pitch, pad_dx, pad_w, pad_len)); k += 1
    if epad:
        pads.append(Pad(str(k), 0, 0, epad, epad, shape="rect"))
    silk = [(-body / 2 - 0.2, body / 2 + 0.2, -body / 2 - 0.2, body / 2 - 1.0)]  # pin-1 tick
    return Footprint(name, pads, body, body, body_z, style, silk=silk, courtyard_margin=1.0)


def lqfp(n, pitch, body) -> Footprint:
    return quad(f"LQFP-{n}", n, pitch, body / 2 + 0.85, 1.5, 0.55 if pitch == 0.8 else 0.3, body, 1.6)


def qfn(n, pitch, body, epad) -> Footprint:
    return quad(f"QFN-{n}", n, pitch, body / 2 - 0.05, 0.8, 0.25 if pitch <= 0.5 else 0.35, body, 0.9, epad)


def dfn(n, pitch, body_w, body_h, name="DFN") -> Footprint:
    """Two-sided leadless package (DFN / LGA-8 style)."""
    f = dual_row(f"{name}-{n}", n, pitch, body_w / 2 - 0.15, 0.65, 0.3 if pitch <= 0.5 else 0.4, body_w, body_h, 0.9)
    return f


# ---------------------------------------------------------------- modules (castellated)
def esp32_wroom(name="ESP32-WROOM-32E", side_pins=14, bottom_pins=10, body_h=25.5, body_w=18.0, pitch=1.27,
                bottom_y=-10.5, ant_h=ANT_H) -> Footprint:
    pads = []
    k = 1
    x = body_w / 2 - 0.75
    for i in range(side_pins):  # left, top->bottom
        y = bottom_y + (side_pins - 1 - i) * pitch
        pads.append(Pad(str(k), -x, y, 1.5, 0.9, shape="rect")); k += 1
    x0 = -(bottom_pins - 1) / 2 * pitch
    for i in range(bottom_pins):  # bottom, left->right
        pads.append(Pad(str(k), x0 + i * pitch, -body_h / 2 + 0.75, 0.9, 1.5, shape="rect")); k += 1
    for i in range(side_pins):  # right, bottom->top
        y = bottom_y + i * pitch
        pads.append(Pad(str(k), x, y, 1.5, 0.9, shape="rect")); k += 1
    pads.append(Pad(str(k), 0, -2.0, 5.0, 5.0, shape="rect"))  # thermal pad
    silk = _rect_silk(body_w, body_h, 0.1) + [(-body_w / 2, body_h / 2 - ant_h, body_w / 2, body_h / 2 - ant_h)]
    return Footprint(name, pads, body_w, body_h, 3.1, "module", courtyard_margin=0.5, silk=silk, edge="+y",
                     description="Castellated RF module; keep antenna end at board edge")


def esp32_c3_wroom02() -> Footprint:
    pads = []
    pitch = 1.5
    k = 1
    n = 9
    y0 = (n - 1) / 2 * pitch - 3.0
    for i in range(n):
        pads.append(Pad(str(k), -8.25, y0 - i * pitch, 1.5, 0.9, shape="rect")); k += 1
    for i in range(n):
        pads.append(Pad(str(k), 8.25, y0 - (n - 1 - i) * pitch, 1.5, 0.9, shape="rect")); k += 1
    pads.append(Pad(str(k), 0, -3.0, 4.0, 4.0, shape="rect"))
    return Footprint("ESP32-C3-WROOM-02", pads, 18.0, 20.0, 3.2, "module", courtyard_margin=0.5, edge="+y",
                     silk=_rect_silk(18, 20, 0.1) + [(-9, 4.0, 9, 4.0)])


def rf_module(name, w, h, n_left, n_right, pitch=2.0, z=3.0) -> Footprint:
    pads = []
    k = 1
    y0 = (n_left - 1) / 2 * pitch
    for i in range(n_left):
        pads.append(Pad(str(k), -w / 2 + 0.6, y0 - i * pitch, 1.2, 1.2, shape="rect")); k += 1
    y0 = (n_right - 1) / 2 * pitch
    for i in range(n_right):
        pads.append(Pad(str(k), w / 2 - 0.6, -y0 + i * pitch, 1.2, 1.2, shape="rect")); k += 1
    return Footprint(name, pads, w, h, z, "module", courtyard_margin=0.5, silk=_rect_silk(w, h, 0.1))


# ---------------------------------------------------------------- through-hole
def header(cols, rows=1, pitch=2.54, edge=None) -> Footprint:
    pads = []
    k = 1
    x0 = -(cols - 1) / 2 * pitch
    y0 = (rows - 1) / 2 * pitch
    for c in range(cols):
        for r in range(rows):
            pads.append(Pad(str(k), x0 + c * pitch, y0 - r * pitch, 1.7, 1.7, shape="circle" if k > 1 else "rect",
                            layer="through", drill=1.0)); k += 1
    w, h = cols * pitch, rows * pitch
    return Footprint(f"PinHeader_{rows}x{cols:02d}", pads, w, h, 8.5 if rows == 1 else 8.5, "header",
                     silk=_rect_silk(w, h), edge=edge)


def jst_ph(n) -> Footprint:
    pads = []
    x0 = -(n - 1) / 2 * 2.0
    for i in range(n):
        pads.append(Pad(str(i + 1), x0 + i * 2.0, 0, 1.2, 1.75, shape="oval", layer="through", drill=0.75))
    w = 2.0 * (n - 1) + 3.9
    return Footprint(f"JST_PH_B{n}B", pads, w, 4.5, 6.0, "connector", silk=_rect_silk(w, 4.5), edge="-y",
                     courtyard_margin=0.5)


def jst_sh_smd(n=4) -> Footprint:
    pads = []
    x0 = -(n - 1) / 2 * 1.0
    for i in range(n):
        pads.append(Pad(str(i + 1), x0 + i * 1.0, 1.8, 0.6, 1.55, shape="rect"))
    w = (n - 1) + 4.0
    pads.append(Pad("S1", -w / 2 + 0.3, -0.9, 1.2, 1.8, shape="rect"))
    pads.append(Pad("S2", w / 2 - 0.3, -0.9, 1.2, 1.8, shape="rect"))
    return Footprint(f"JST_SH_SM{n:02d}B", pads, w, 4.2, 4.3, "connector", edge="-y", courtyard_margin=0.5)


def usb_c_16p() -> Footprint:
    """USB-C 2.0 receptacle, 16 pins, HRO TYPE-C-31-M-12 style. Opening toward -y."""
    ypin = 2.4
    pins = [("A1B12", -3.25, 0.6), ("A4B9", -2.45, 0.6), ("B8", -1.75, 0.3), ("A5", -1.25, 0.3), ("B7", -0.75, 0.3),
            ("A6", -0.25, 0.3), ("A7", 0.25, 0.3), ("B6", 0.75, 0.3), ("A8", 1.25, 0.3), ("B5", 1.75, 0.3),
            ("B4A9", 2.45, 0.6), ("B1A12", 3.25, 0.6)]
    pads = [Pad(nm, x, ypin, w, 1.2, shape="roundrect", escape=None if w > 0.5 else "both") for nm, x, w in pins]
    for i, (x, y) in enumerate([(-4.32, 1.6), (4.32, 1.6), (-4.32, -2.0), (4.32, -2.0)]):
        pads.append(Pad(f"S{i + 1}", x, y, 1.0, 2.1, shape="oval", layer="through", drill=0.65))
    silk = [(-4.47, 3.0, 4.47, 3.0)]
    return Footprint("USB_C_Receptacle_16P", pads, 8.94, 7.35, 3.3, "usb", edge="-y", courtyard_margin=1.2, silk=silk)


def barrel_jack() -> Footprint:
    pads = [Pad("1", 0, 3.0, 3.5, 3.0, shape="oval", layer="through", drill=1.3),
            Pad("2", 0, -3.0, 3.5, 3.0, shape="oval", layer="through", drill=1.3),
            Pad("3", 4.7, 0, 3.0, 3.5, shape="oval", layer="through", drill=1.3)]
    return Footprint("BarrelJack_DC-005", pads, 9.0, 14.2, 11.0, "connector", edge="-y", courtyard_margin=0.5,
                     silk=_rect_silk(9.0, 14.2))


def screw_terminal(n, pitch=5.08) -> Footprint:
    x0 = -(n - 1) / 2 * pitch
    pads = [Pad(str(i + 1), x0 + i * pitch, 0, 2.6, 2.6, shape="circle" if i else "rect", layer="through", drill=1.3)
            for i in range(n)]
    w = n * pitch
    return Footprint(f"ScrewTerminal_1x{n:02d}_P{pitch}", pads, w, 8.0, 10.0, "connector", edge="-y",
                     silk=_rect_silk(w, 8.0), courtyard_margin=0.5)


def to92_wide() -> Footprint:
    pads = [Pad(str(i + 1), (i - 1) * 2.54, 0, 1.6, 1.6, shape="circle" if i else "rect", layer="through", drill=0.8)
            for i in range(3)]
    return Footprint("TO-92_Inline_Wide", pads, 6.0, 4.5, 5.0, "tht", silk=[(-3, -2.25, 3, -2.25)])


def to220() -> Footprint:
    pads = [Pad(str(i + 1), (i - 1) * 2.54, 0, 1.8, 2.4, shape="oval", layer="through", drill=1.0) for i in range(3)]
    return Footprint("TO-220-3_Vertical", pads, 10.2, 4.6, 15.0, "tht", silk=_rect_silk(10.2, 4.6))


def tact_switch_6x6() -> Footprint:
    pads = [Pad("1", -3.25, 2.25, 2.0, 2.0, shape="circle", layer="through", drill=1.0),
            Pad("2", 3.25, 2.25, 2.0, 2.0, shape="circle", layer="through", drill=1.0),
            Pad("3", -3.25, -2.25, 2.0, 2.0, shape="circle", layer="through", drill=1.0),
            Pad("4", 3.25, -2.25, 2.0, 2.0, shape="circle", layer="through", drill=1.0)]
    return Footprint("SW_PUSH_6mm", pads, 6.0, 6.0, 5.0, "switch", silk=_rect_silk(6, 6))


def tact_switch_smd() -> Footprint:
    pads = [Pad("1", -3.0, 1.85, 1.55, 1.3, shape="rect"), Pad("2", 3.0, 1.85, 1.55, 1.3, shape="rect"),
            Pad("3", -3.0, -1.85, 1.55, 1.3, shape="rect"), Pad("4", 3.0, -1.85, 1.55, 1.3, shape="rect")]
    return Footprint("SW_SPST_TL3342", pads, 4.5, 4.5, 3.5, "switch", silk=_rect_silk(4.5, 4.5))


def slide_switch() -> Footprint:
    pads = [Pad(str(i + 1), (i - 1) * 2.54, 0, 1.5, 1.5, shape="circle" if i else "rect", layer="through", drill=0.9)
            for i in range(3)]
    pads += [Pad("S1", -4.5, 0, 1.6, 1.6, shape="circle", layer="through", drill=1.0, plated=True),
             Pad("S2", 4.5, 0, 1.6, 1.6, shape="circle", layer="through", drill=1.0, plated=True)]
    return Footprint("SW_Slide_SS12D00", pads, 9.0, 3.6, 5.0, "switch", edge="-y", silk=_rect_silk(9.0, 3.6))


def rotary_encoder() -> Footprint:
    pads = [Pad("A", -2.5, 7.5, 1.6, 2.0, shape="oval", layer="through", drill=1.0),
            Pad("C", 0, 7.5, 1.6, 2.0, shape="oval", layer="through", drill=1.0),
            Pad("B", 2.5, 7.5, 1.6, 2.0, shape="oval", layer="through", drill=1.0),
            Pad("S1", -2.5, -7.0, 1.6, 2.0, shape="oval", layer="through", drill=1.0),
            Pad("S2", 2.5, -7.0, 1.6, 2.0, shape="oval", layer="through", drill=1.0),
            Pad("M1", -5.6, 0, 2.8, 2.0, shape="oval", layer="through", drill=1.6, plated=True),
            Pad("M2", 5.6, 0, 2.8, 2.0, shape="oval", layer="through", drill=1.6, plated=True)]
    return Footprint("RotaryEncoder_EC11", pads, 12.4, 13.4, 14.5, "switch", silk=_rect_silk(12.4, 13.4))


def potentiometer() -> Footprint:
    pads = [Pad(str(i + 1), (i - 1) * 2.54, 0, 1.6, 1.6, shape="circle" if i else "rect", layer="through", drill=0.9)
            for i in range(3)]
    return Footprint("Potentiometer_3386P", pads, 9.5, 9.5, 5.0, "tht", silk=_rect_silk(9.5, 9.5))


def buzzer_12mm() -> Footprint:
    pads = [Pad("1", -3.8, 0, 1.6, 1.6, shape="rect", layer="through", drill=0.9),
            Pad("2", 3.8, 0, 1.6, 1.6, shape="circle", layer="through", drill=0.9)]
    return Footprint("Buzzer_12x9.5", pads, 12.0, 12.0, 9.5, "electrolytic", silk=[(-6, -6, 6, -6), (6, -6, 6, 6), (6, 6, -6, 6), (-6, 6, -6, -6)])


def relay_srd() -> Footprint:
    pads = [Pad("1", -6.0, 7.5, 2.2, 2.2, shape="circle", layer="through", drill=1.3),
            Pad("2", 6.0, 7.5, 2.2, 2.2, shape="circle", layer="through", drill=1.3),
            Pad("3", 0, -6.5, 2.2, 2.2, shape="circle", layer="through", drill=1.3),
            Pad("4", -6.0, -6.5, 2.2, 2.2, shape="circle", layer="through", drill=1.3),
            Pad("5", 6.0, -6.5, 2.2, 2.2, shape="circle", layer="through", drill=1.3)]
    return Footprint("Relay_SRD-05VDC", pads, 19.0, 15.5, 15.5, "tht", silk=_rect_silk(19, 15.5))


def mounting_hole_m3() -> Footprint:
    return Footprint("MountingHole_3.2mm_M3", [Pad("1", 0, 0, 3.4, 3.4, shape="circle", layer="through", drill=3.2, plated=False)],
                     6.4, 6.4, 0, "hole", courtyard_margin=0.0)


def test_point() -> Footprint:
    return Footprint("TestPoint_1.5mm", [Pad("1", 0, 0, 1.5, 1.5, shape="circle")], 1.5, 1.5, 0.0, "passive")


# ---------------------------------------------------------------- misc SMD
def electrolytic_smd(d=6.3) -> Footprint:
    return Footprint(f"CP_Elec_{d}x5.4", [Pad("1", -2.7, 0, 3.0, 1.6, shape="rect"), Pad("2", 2.7, 0, 3.0, 1.6, shape="rect")],
                     d + 0.3, d + 0.3, 5.4, "electrolytic", silk=[(-3.3, 3.3, 3.3, 3.3)])


def inductor_4x4() -> Footprint:
    return Footprint("L_4x4", [Pad("1", -1.7, 0, 1.6, 4.4, shape="rect"), Pad("2", 1.7, 0, 1.6, 4.4, shape="rect")],
                     4.0, 4.0, 2.1, "chip", silk=[(-2.0, 2.3, 2.0, 2.3), (-2.0, -2.3, 2.0, -2.3)])


def sma_diode() -> Footprint:
    return Footprint("D_SMA", [Pad("1", -2.0, 0, 2.5, 1.8, shape="rect"), Pad("2", 2.0, 0, 2.5, 1.8, shape="rect")],
                     4.3, 2.6, 2.3, "chip", silk=[(-2.3, 1.6, 2.3, 1.6), (-2.3, -1.6, 2.3, -1.6), (-2.3, -1.6, -2.3, 1.6)])


def sod123() -> Footprint:
    return Footprint("D_SOD-123", [Pad("1", -1.635, 0, 0.9, 1.2, shape="rect"), Pad("2", 1.635, 0, 0.9, 1.2, shape="rect")],
                     2.7, 1.6, 1.1, "chip", silk=[(-1.5, 1.0, 1.5, 1.0), (-1.5, -1.0, 1.5, -1.0), (-1.5, -1.0, -1.5, 1.0)])


def led_5050() -> Footprint:
    pads = [Pad("1", -2.45, 1.6, 1.5, 1.0, shape="rect"), Pad("2", -2.45, -1.6, 1.5, 1.0, shape="rect"),
            Pad("3", 2.45, -1.6, 1.5, 1.0, shape="rect"), Pad("4", 2.45, 1.6, 1.5, 1.0, shape="rect")]
    return Footprint("LED_WS2812B_5050", pads, 5.0, 5.0, 1.6, "led", silk=_rect_silk(5, 5, 0.1))


def crystal_hc49_smd() -> Footprint:
    return Footprint("Crystal_HC49-SD", [Pad("1", -4.85, 0, 5.6, 1.9, shape="rect"), Pad("2", 4.85, 0, 5.6, 1.9, shape="rect")],
                     11.4, 4.7, 4.0, "crystal", silk=_rect_silk(11.4, 4.7))


def crystal_3225() -> Footprint:
    pads = [Pad("1", -1.1, -0.8, 1.4, 1.2, shape="rect"), Pad("2", 1.1, -0.8, 1.4, 1.2, shape="rect"),
            Pad("3", 1.1, 0.8, 1.4, 1.2, shape="rect"), Pad("4", -1.1, 0.8, 1.4, 1.2, shape="rect")]
    return Footprint("Crystal_SMD_3225-4Pin", pads, 3.2, 2.5, 0.8, "crystal", silk=_rect_silk(3.2, 2.5, 0.1))


def crystal_3215() -> Footprint:
    return Footprint("Crystal_SMD_3215-2Pin", [Pad("1", -1.2, 0, 1.4, 1.6, shape="rect"), Pad("2", 1.2, 0, 1.4, 1.6, shape="rect")],
                     3.2, 1.5, 0.9, "crystal", silk=_rect_silk(3.2, 1.5, 0.1))


def microsd_slot() -> Footprint:
    pads = []
    names = ["DAT2", "CD/DAT3", "CMD", "VDD", "CLK", "VSS", "DAT0", "DAT1"]
    x0 = -3.85
    for i, nm in enumerate(names):
        pads.append(Pad(str(i + 1), x0 + i * 1.1, 6.0, 0.7, 1.6, shape="rect"))
    pads.append(Pad("9", 5.5, 6.0, 0.7, 1.6, shape="rect"))  # card detect
    for i, (x, y) in enumerate([(-7.0, 5.0), (7.0, 5.0), (-7.0, -4.5), (7.0, -4.5)]):
        pads.append(Pad(f"S{i + 1}", x, y, 1.4, 1.8, shape="rect"))
    return Footprint("microSD_Push", pads, 14.7, 14.5, 1.85, "connector", edge="-y", courtyard_margin=0.5,
                     silk=_rect_silk(14.7, 14.5))


def battery_holder_18650() -> Footprint:
    pads = [Pad("1", -34.5, 0, 3.0, 3.0, shape="rect", layer="through", drill=1.5),
            Pad("2", 34.5, 0, 3.0, 3.0, shape="circle", layer="through", drill=1.5)]
    return Footprint("BatteryHolder_18650", pads, 77.0, 20.0, 15.0, "tht", silk=_rect_silk(77, 20))


def coin_cell_cr2032() -> Footprint:
    return Footprint("BatteryHolder_CR2032_SMD", [Pad("1", -11.0, 0, 3.5, 5.0, shape="rect"), Pad("2", 11.0, 0, 3.5, 5.0, shape="rect")],
                     20.0, 22.0, 5.4, "electrolytic", silk=_rect_silk(20, 22))


def fiducial() -> Footprint:
    return Footprint("Fiducial_1mm", [Pad("1", 0, 0, 1.0, 1.0, shape="circle")], 1.0, 1.0, 0.0, "hole")


REGISTRY: dict[str, Footprint] = {}


def register(fp: Footprint) -> Footprint:
    REGISTRY[fp.name] = fp
    return fp


def get(name: str) -> Footprint:
    return REGISTRY[name]
