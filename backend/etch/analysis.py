"""Physics-flavoured checks: steady-state thermal solve, DC power-rail IR drop, optional ngspice transient."""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable

import numpy as np

from .model import Board
from .power_routing import width_summary

RHO_CU = 1.68e-8  # ohm·m
T_CU = 35e-6  # 1 oz copper, m
AMBIENT = 25.0


def component_power(board: Board, c) -> float:
    p = c.part.power_w
    if c.part.category == "power":
        # LDO: dissipation = (Vin - Vout) * Iout
        vin = vout = iout = None
        for pad in c.footprint.pads:
            net = board.net_of(c.ref, pad.num)
            if not net or net.cls != "power":
                continue
            ptype = c.part.pin_by(pad.num)
            if not ptype:
                continue
            if ptype[2] == "power_in":
                vin = net.voltage or vin
            elif ptype[2] == "power_out":
                vout = net.voltage or vout
                iout = net.current_ma or iout
        if vin and vout and iout and vin > vout and "ldo" in (c.part.description.lower() + c.part.name.lower()) or \
                (vin and vout and iout and c.part.footprint.name in ("SOT-223", "SOT-23", "SOT-23-5", "TO-220-3_Vertical")):
            p = max(p, (vin - vout) * iout / 1000.0)
    return p


def thermal(board: Board, on_frame: Callable[[dict], None], frames: int = 24, iters: int = 360):
    """2-D steady-state conduction+convection solve on a ~1 mm grid, streamed as frames."""
    cell = 1.0
    nx, ny = int(math.ceil(board.width / cell)), int(math.ceil(board.height / cell))
    q = np.zeros((ny, nx))
    src = {}
    for c in board.components:
        p = component_power(board, c)
        if p <= 0:
            continue
        bx, by, bw, bh = c.courtyard_abs()
        i0, i1 = max(0, int(bx / cell)), min(nx - 1, int((bx + bw) / cell))
        j0, j1 = max(0, int(by / cell)), min(ny - 1, int((by + bh) / cell))
        n = max(1, (i1 - i0 + 1) * (j1 - j0 + 1))
        q[j0:j1 + 1, i0:i1 + 1] += p / n
        src[c.ref] = (p, (j0 + j1) // 2, (i0 + i1) // 2)
    # copper density raises in-plane conductivity: bottom pour ~ full, traces add a little
    k = np.full((ny, nx), 1.0)
    for t in board.traces:
        for (x, y) in t.points:
            i, j = min(nx - 1, int(x / cell)), min(ny - 1, int(y / cell))
            k[j, i] += 0.6
    k = np.clip(k, 1.0, 3.0)
    h = 0.055  # convection + radiation to ambient, per cell
    gain = 62.0  # W -> K scaling for a small FR4 board in still air
    T = np.full((ny, nx), AMBIENT)
    every = max(1, iters // frames)
    for it in range(iters):
        Tp = np.pad(T, 1, mode="edge")
        nb = (Tp[:-2, 1:-1] + Tp[2:, 1:-1] + Tp[1:-1, :-2] + Tp[1:-1, 2:])
        T = (k * nb + gain * q + h * AMBIENT) / (4 * k + h)
        if it % every == 0 or it == iters - 1:
            hot = sorted(((float(T[j, i]), ref) for ref, (p, j, i) in src.items()), reverse=True)[:4]
            on_frame({
                "type": "thermal", "frame": it // every, "total": frames, "cols": nx, "rows": ny,
                "grid": [round(float(v), 1) for v in T.ravel()], "min_c": round(float(T.min()), 1), "max_c": round(float(T.max()), 1),
                "hotspots": [{"ref": ref, "c": round(t, 1)} for t, ref in hot],
            })
    return {"max_c": round(float(T.max()), 1), "hotspots": [{"ref": ref, "c": round(float(T[j, i]), 1)} for ref, (p, j, i) in src.items()]}


def power_rails(board: Board) -> list[dict]:
    rails = []
    for n in board.nets:
        if n.cls != "power":
            continue
        length = 0.0
        R = 0.0
        wmin = 9.9
        for t in board.traces:
            if t.net != n.name:
                continue
            L = t.length
            length += L
            wmin = min(wmin, t.width)
            R += RHO_CU * (L / 1000.0) / (t.width / 1000.0 * T_CU)
        nvias = sum(1 for v in board.vias if v.net == n.name)
        R += nvias * 0.0008
        I = (n.current_ma or 100) / 1000.0
        # worst-case: the whole current flows through half the total copper path
        drop = I * R * 0.5
        widths = width_summary(board, n)
        drop_ok = drop < 0.02 * (n.voltage or 3.3)
        rails.append({"net": n.name, "voltage": n.voltage, "current_ma": n.current_ma or 100, "length_mm": round(length, 1),
                      "width_mm": round(wmin if wmin < 9 else 0, 2), "resistance_mohm": round(R * 1000, 1),
                      "drop_mv": round(drop * 1000, 1), "vias": nvias, **widths, "drop_ok": drop_ok,
                      "ok": drop_ok and widths['width_ok']})
    return rails


def ngspice_available() -> bool:
    return shutil.which("ngspice") is not None


def _parse_value(s: str, default: float) -> float:
    m = re.match(r"\s*([0-9.]+)\s*([a-zA-Zµ]*)", s or "")
    if not m:
        return default
    v = float(m.group(1))
    mult = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "": 1}.get(m.group(2).lower().rstrip("fh").replace("uf", "u"), None)
    if mult is None:
        mult = {"p": 1e-12, "n": 1e-9, "u": 1e-6}.get(m.group(2).lower()[:1], 1)
    return v * mult


def spice_rail_step(board: Board) -> dict | None:
    """Transient sim of the main regulated rail under a load step using the actual decoupling capacitance on the board.
    Regulator modelled as a voltage source with output impedance + bandwidth limit (behavioural)."""
    if not ngspice_available():
        return None
    rails = [n for n in board.nets if n.cls == "power" and n.voltage and n.voltage < 4.5]
    if not rails:
        return None
    rail = max(rails, key=lambda n: len(n.pins))
    # sum capacitance on the rail
    ctotal = 0.0
    for ref, pnum in rail.pins:
        c = board.comp(ref)
        if c and c.ref.startswith("C"):
            ctotal += _parse_value(c.value, 100e-9)
    ctotal = max(ctotal, 1e-6)
    # trace resistance along the rail
    R = 0.02
    for t in board.traces:
        if t.net == rail.name:
            R += RHO_CU * (t.length / 1000.0) / (t.width / 1000.0 * T_CU)
    I = (rail.current_ma or 300) / 1000.0
    vout = rail.voltage
    esr = 0.01
    net = f"""* ETCH rail step: {rail.name}
Vreg ideal 0 DC {vout}
Rreg ideal reg 0.15
Lreg reg rail_in 2.2u
Rtrace rail_in rail {R:.5f}
Cbulk rail cesr {ctotal:.3e}
Resr cesr 0 {esr}
Iload rail 0 PULSE({I * 0.2:.4f} {I:.4f} 200u 2u 2u 400u 1m)
.tran 1u 1.2m
.control
set filetype=ascii
run
wrdata {{OUT}} v(rail) i(Vreg)
.endc
.end
"""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out.txt")
        cir = os.path.join(d, "rail.cir")
        with open(cir, "w") as f:
            f.write(net.replace("{OUT}", out))
        try:
            subprocess.run(["ngspice", "-b", cir], capture_output=True, timeout=30, cwd=d)
        except Exception:
            return None
        if not os.path.exists(out):
            return None
        xs, ys, iss = [], [], []
        with open(out) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        xs.append(float(parts[0]) * 1000)
                        ys.append(float(parts[1]))
                        iss.append(-float(parts[3]) * 1000)
                    except ValueError:
                        pass
        if not xs:
            return None
        step = max(1, len(xs) // 300)
        xs, ys, iss = xs[::step], ys[::step], iss[::step]
        return {"type": "spice", "title": f"{rail.name} rail load step ({int(I * 200)}→{int(I * 1000)} mA), C={ctotal * 1e6:.1f} µF",
                "x_label": "t (ms)", "y_label": "V", "engine": "ngspice",
                "series": [{"name": f"V({rail.name})", "x": [round(x, 4) for x in xs], "y": [round(y, 4) for y in ys]},
                           {"name": "I_load (mA)", "x": [round(x, 4) for x in xs], "y": [round(y, 2) for y in iss], "axis": "right"}],
                "min_v": round(min(ys), 3), "nominal_v": vout, "undershoot_mv": round((vout - min(ys)) * 1000, 1)}
