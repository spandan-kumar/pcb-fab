"""The hardware-architect agent: prompt construction, streaming, JSON parsing and validation → Board."""
from __future__ import annotations

import difflib
import json
import re
from typing import Awaitable, Callable

from . import llm
from .catalog import CATALOG, catalog_prompt
from .model import Board, Component, Net
from .placement import size_board

SYSTEM = """You are ETCH, a senior electronics hardware architect. A user describes a device in plain language; you design a
complete, manufacturable 2-layer PCB: pick the architecture, choose every component from the PARTS CATALOG below, and write the
full netlist. Your output is consumed by an automated placer/router/DRC/Gerber pipeline, so it must be exact.

## Output format (strict)
1. First, a markdown section titled `## Reasoning`: think out loud like an experienced EE reviewing requirements → architecture →
   power tree → MCU & I/O map → peripherals → protection/programming → trade-offs. 200–350 words, concrete numbers (currents,
   voltages, pull-up values). No JSON here.
2. Then exactly ONE fenced ```json block with this schema (no comments, no trailing commas):
{
  "name": "ShortName",                       // ≤ 12 chars, no spaces, used as board name
  "tagline": "one line",
  "summary": "2-3 sentences for a non-engineer",
  "board": {"width": 58, "height": 42, "mounting_holes": true},   // mm; keep compact but routable
  "power": {"input": "USB-C 5 V", "rails": [{"net": "5V", "voltage": 5.0, "current_ma": 800}, {"net": "3V3", "voltage": 3.3, "current_ma": 500}]},
  "components": [{"ref": "U1", "part": "esp32-wroom-32e", "value": "", "purpose": "why it is here (≤ 12 words)"}],
  "nets": [{"name": "GND", "cls": "gnd", "pins": ["U1.1", "U1.15", "C1.2"]}],
  "notes": ["design notes / assumptions / things to verify"],
  "estimated_cost_usd": 6.4
}

## Hard rules
- Use ONLY `part` ids from the catalog. Pins are written `REF.PINNUMBER` (numbers as listed, e.g. `U1.33`, `J1.A5`). Pin names are
  also accepted for uniqueness (`U1.IO21`), but prefer numbers.
- Reference designators: R1.., C1.., U1.., J1.., D1.., SW1.., Y1.., L1.., F1.., Q1.., K1.., H1.. Unique.
- Every net has ≥ 2 pins. Ground net is named exactly `GND` with `cls: "gnd"`. Power rails use `cls: "power"` and appear in `power.rails`.
  Other nets: `signal`, `analog`, or `highspeed` (USB D+/D-).
- A pin may appear in only one net. Do not connect pins marked NC. Do not list unconnected pins.
- Component count: 12–38 total (routability on a 2-layer board). Prefer one MCU/module. Passives: 0603 by default, 0805 for ≥ 10 uF.
- Always include: decoupling (100 nF per IC power pin, 10 uF bulk per rail), regulator in/out caps, pull-ups on I2C (4.7k),
  series resistors for LEDs (1k at 3.3 V), a power LED, and a programming path (USB-C + CH340C UART for ESP32-WROOM; native USB for
  ESP32-S3/C3; ICSP header for AVR; SWD header for STM32). ESP32: EN 10k pull-up + 100 nF, BOOT (IO0) button, RESET (EN) button.
- USB-C: two separate 5.1k CC pull-downs (CC1 and CC2, one resistor each), D+ pads tied together (A6+B6), D- pads (A7+B7),
  both VBUS pads on the 5 V net, shield pads to GND. Add `tvs-usblc6` on D+/D-/VBUS.
- Mounting holes: set `board.mounting_holes` true and do NOT add `mount-m3` components (the pipeline adds 4 automatically).
- Values: resistors like "10k", "4.7k", "330"; caps "100nF", "10uF"; LEDs by colour ("green"); crystals "16MHz".
- Estimate board size from part count (≈ 1.4 cm² per IC, 0.15 cm² per passive, plus connectors). Typical: 40×30 to 80×60 mm.
- Wi-Fi modules keep their antenna at a board edge (the pipeline handles this).
- Choose sensible currents: ESP32 Wi-Fi ≈ 500 mA peak on 3V3; LDO input current ≈ output current.
- If the user asks for something not in the catalog, use the closest catalog part (e.g. a header for an off-board module) and say so in notes.

## PARTS CATALOG (id, name, [footprint], pins as number:name — hints after the dash)
""" + catalog_prompt()


def _extract_json(text: str) -> dict:
    m = list(re.finditer(r"```json\s*(\{.*?\})\s*```", text, re.S))
    raw = m[-1].group(1) if m else None
    if raw is None:
        # fall back: largest {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0:
            raise ValueError("no JSON in agent output")
        raw = text[start:end + 1]
    raw = re.sub(r"//[^\n]*", "", raw)
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    return json.loads(raw)


def _cls_for(name: str, given: str | None, rails: dict) -> str:
    if given in ("gnd", "power", "signal", "analog", "highspeed"):
        return given
    n = name.upper()
    if n in ("GND", "VSS", "AGND", "PGND", "DGND"):
        return "gnd"
    if n in rails or re.match(r"^(V?BUS|VIN|VBAT|BAT\+?|VCC|VDD|\d+V\d*|\d+V|V\d+)$", n) or n.startswith(("3V", "5V", "12V", "VBUS", "VBAT", "VIN", "VCC")):
        return "power"
    if "USB" in n or n.startswith(("D+", "D-", "DP", "DM")):
        return "highspeed"
    return "signal"


def build_board(spec: dict, color: str, notes: list[str]) -> tuple[Board, dict]:
    """Validate/repair the agent's spec and construct a Board. Returns (board, design_json)."""
    name = re.sub(r"[^A-Za-z0-9_-]", "", str(spec.get("name", "ETCH"))).strip() or "ETCH"
    board_spec = spec.get("board", {}) or {}
    bw = float(board_spec.get("width", 50) or 50)
    bh = float(board_spec.get("height", 40) or 40)
    mounting = bool(board_spec.get("mounting_holes", True))
    b = Board(width=bw, height=bh, color=color, mounting_holes=mounting, name=name[:12].upper())
    rails = {}
    for r in (spec.get("power", {}) or {}).get("rails", []) or []:
        try:
            rails[str(r["net"]).upper()] = (float(r.get("voltage", 0) or 0), float(r.get("current_ma", 0) or 0))
        except Exception:
            pass
    # components
    used_refs = set()
    counters: dict[str, int] = {}
    ref_map = {}
    for cs in spec.get("components", []) or []:
        pid = str(cs.get("part", "")).strip().lower()
        part = CATALOG.get(pid)
        if part is None:
            cand = difflib.get_close_matches(pid, list(CATALOG.keys()), n=1, cutoff=0.5)
            if not cand:
                names = {p.name.lower(): p.id for p in CATALOG.values()}
                cand2 = difflib.get_close_matches(pid, list(names.keys()), n=1, cutoff=0.5)
                cand = [names[cand2[0]]] if cand2 else []
            if cand:
                notes.append(f"Unknown part `{pid}` mapped to `{cand[0]}`")
                part = CATALOG[cand[0]]
            else:
                notes.append(f"Dropped unknown part `{pid}` ({cs.get('ref')})")
                continue
        if part.id == "mount-m3":
            continue
        ref = str(cs.get("ref") or "").strip().upper()
        if not ref or ref in used_refs:
            k = counters.get(part.ref_prefix, 0) + 1
            while f"{part.ref_prefix}{k}" in used_refs:
                k += 1
            counters[part.ref_prefix] = k
            new_ref = f"{part.ref_prefix}{k}"
            if ref:
                ref_map[ref] = new_ref
            ref = new_ref
        used_refs.add(ref)
        val = str(cs.get("value", "") or "")
        if not val and part.id.startswith(("r-", "c-", "led-")):
            val = part.value
        b.components.append(Component(ref, part, val, str(cs.get("purpose", "") or "")))
    if not b.components:
        raise ValueError("agent produced no valid components")
    # nets
    seen_pins = set()
    nets: dict[str, Net] = {}
    for ns in spec.get("nets", []) or []:
        nname = str(ns.get("name", "")).strip().replace(" ", "_")
        if not nname:
            continue
        if nname.upper() in ("GND", "VSS", "GROUND"):
            nname = "GND"
        pins = []
        for ps in ns.get("pins", []) or []:
            if not isinstance(ps, str) or "." not in ps:
                continue
            ref, pin = ps.split(".", 1)
            ref = ref_map.get(ref.strip().upper(), ref.strip().upper())
            c = b.comp(ref)
            if c is None:
                notes.append(f"Net {nname}: unknown ref {ref}")
                continue
            pr = c.part.pin_by(pin.strip())
            if pr is None:
                notes.append(f"Net {nname}: {ref} has no pin {pin}")
                continue
            if pr[2] == "nc":
                continue
            key = (ref, pr[0])
            if key in seen_pins:
                continue
            seen_pins.add(key)
            pins.append(key)
        if not pins:
            continue
        if nname in nets:
            nets[nname].pins.extend(pins)
        else:
            cls = _cls_for(nname, ns.get("cls"), rails)
            v, i = rails.get(nname.upper(), (0.0, 0.0))
            if cls == "power" and not v:
                v = 5.0 if "5" in nname else 3.3 if "3" in nname else 0.0
            nets[nname] = Net(nname, pins, cls, v, i or (300 if cls == "power" else 0))
    # tie identical pad groups (USB-C D+/D- duplicates) automatically when the agent only listed one
    b.nets = [n for n in nets.values() if len(n.pins) >= 2]
    if not any(n.cls == "gnd" for n in b.nets):
        notes.append("No GND net found — the bottom pour will be unconnected")
    # mounting holes
    w, h = size_board(b, bw, bh)
    b.width, b.height = w, h
    if mounting:
        from .catalog import CATALOG as C
        for k, (x, y) in enumerate([(3.5, 3.5), (w - 3.5, 3.5), (3.5, h - 3.5), (w - 3.5, h - 3.5)], 1):
            hc = Component(f"H{k}", C["mount-m3"], "", "mounting hole", x, y, 0, fixed=True)
            b.components.append(hc)
    # silkscreen texts
    b.texts = [{"text": f"{b.name} v1.0", "x": w / 2, "y": h - 2.2, "size": 1.1, "layer": "F.SilkS", "rot": 0},
               {"text": "ETCH", "x": w / 2, "y": 2.0, "size": 0.9, "layer": "F.SilkS", "rot": 0}]
    design = {
        "name": b.name, "tagline": str(spec.get("tagline", "")), "summary": str(spec.get("summary", "")),
        "board": {"width": w, "height": h, "corner_radius": b.corner_radius, "mounting_holes": mounting, "color": color, "layers": 2},
        "power": {"input": (spec.get("power", {}) or {}).get("input", ""), "rails": [n.name for n in b.nets if n.cls == "power"]},
        "estimated_cost_usd": float(spec.get("estimated_cost_usd", 0) or sum(c.part.price for c in b.components)),
        "notes": (spec.get("notes", []) or []) + notes,
    }
    return b, design


def user_prompt(prompt: str) -> str:
    return f"Design brief:\n{prompt.strip()}\n\nFollow the output format exactly."


async def run_agent(prompt: str, color: str, on_thought: Callable[[str], Awaitable[None]], prefer_cache=False) -> tuple[Board, dict, str]:
    """Stream the agent, then build the board. Returns (board, design, raw_text)."""
    user = user_prompt(prompt)
    buf = []
    in_json = False

    async def on_delta(t: str):
        nonlocal in_json
        buf.append(t)
        if in_json:
            return
        joined = "".join(buf[-6:])
        if "```json" in joined or "```" in t:
            in_json = True
            # emit whatever prose came before the fence in this delta
            head = t.split("```")[0]
            if head:
                await on_thought(head)
            return
        await on_thought(t)

    text = await llm.stream_completion(SYSTEM, user, on_delta, prefer_cache=prefer_cache)
    spec = _extract_json(text)
    notes: list[str] = []
    board, design = build_board(spec, color, notes)
    return board, design, text
