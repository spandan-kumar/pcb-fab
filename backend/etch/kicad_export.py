"""Write a KiCad 9/10 .kicad_pcb (+ .kicad_pro with design rules) and optionally run kicad-cli DRC / Gerber export."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

from .model import Board

KICAD_CLI_CANDIDATES = [
    shutil.which("kicad-cli") or "",
    os.path.expanduser("~/Applications/KiCad.app/Contents/MacOS/kicad-cli"),
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/Applications/KiCad.app/Contents/MacOS/kicad-cli",
]


def kicad_cli() -> str | None:
    for p in KICAD_CLI_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def _u():
    return str(uuid.uuid4())


def _f(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


LAYERS = """  (layers
    (0 "F.Cu" signal)
    (2 "B.Cu" signal)
    (9 "F.Adhes" user "F.Adhesive")
    (11 "B.Adhes" user "B.Adhesive")
    (13 "F.Paste" user)
    (15 "B.Paste" user)
    (5 "F.SilkS" user "F.Silkscreen")
    (7 "B.SilkS" user "B.Silkscreen")
    (1 "F.Mask" user)
    (3 "B.Mask" user)
    (17 "Dwgs.User" user "User.Drawings")
    (19 "Cmts.User" user "User.Comments")
    (21 "Eco1.User" user "User.Eco1")
    (23 "Eco2.User" user "User.Eco2")
    (25 "Edge.Cuts" user)
    (27 "Margin" user)
    (31 "F.CrtYd" user "F.Courtyard")
    (29 "B.CrtYd" user "B.Courtyard")
    (35 "F.Fab" user)
    (33 "B.Fab" user)
  )"""


def write_kicad_pcb(board: Board, keepouts: list[tuple[float, float, float, float]] | None = None) -> str:
    H = board.height

    def Y(y):  # flip to KiCad y-down
        return _f(H - y)

    net_ids = {n.name: i + 1 for i, n in enumerate(board.nets)}
    out = [f'(kicad_pcb\n  (version 20241229)\n  (generator "etch")\n  (generator_version "9.0")',
           "  (general\n    (thickness 1.6)\n    (legacy_teardrops no)\n  )", '  (paper "A4")', LAYERS,
           "  (setup\n    (pad_to_mask_clearance 0.05)\n    (allow_soldermask_bridges_in_footprints no)\n    (tenting front back)\n"
           "    (pcbplotparams\n      (layerselection 0x00000000_00000000_55555555_5755f5ff)\n      (plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000)\n"
           "      (disableapertmacros no)\n      (usegerberextensions yes)\n      (usegerberattributes yes)\n      (usegerberadvancedattributes yes)\n"
           "      (creategerberjobfile yes)\n      (dashed_line_dash_ratio 12.000000)\n      (dashed_line_gap_ratio 3.000000)\n      (svgprecision 4)\n"
           "      (plotframeref no)\n      (mode 1)\n      (useauxorigin no)\n      (hpglpennumber 1)\n      (hpglpenspeed 20)\n      (hpglpendiameter 15.000000)\n"
           "      (pdf_front_fp_property_popups yes)\n      (pdf_back_fp_property_popups yes)\n      (pdf_metadata yes)\n      (pdf_single_document no)\n"
           "      (dxfpolygonmode yes)\n      (dxfimperialunits yes)\n      (dxfusepcbnewfont yes)\n      (psnegative no)\n      (psa4output no)\n"
           "      (plot_black_and_white yes)\n      (sketchpadsonfab no)\n      (plotpadnumbers no)\n      (hidednp no)\n      (subtractmaskfromsilk no)\n"
           "      (outputformat 1)\n      (mirror no)\n      (drillshape 0)\n      (scaleselection 1)\n      (outputdirectory \"gerbers/\")\n    )\n  )",
           '  (net 0 "")']
    for n in board.nets:
        out.append(f'  (net {net_ids[n.name]} "{n.name}")')

    for c in board.components:
        fp = c.footprint
        cx, cy, cw, ch = fp.courtyard
        smd = all(p.layer != "through" for p in fp.pads)
        lines = [f'  (footprint "etch:{fp.name}"\n    (layer "F.Cu")\n    (uuid "{_u()}")\n    (at {_f(c.x)} {Y(c.y)} {c.rot})',
                 f'    (descr "{fp.description or fp.name}")',
                 f'    (property "Reference" "{c.ref}"\n      (at 0 {_f(-(ch / 2 + 0.9))} {c.rot})\n      (layer "F.SilkS")\n      (uuid "{_u()}")\n'
                 f'      (effects (font (size 0.7 0.7) (thickness 0.12)))\n    )',
                 f'    (property "Value" "{(c.value or c.part.name).replace(chr(34), "")}"\n      (at 0 {_f(ch / 2 + 0.9)} {c.rot})\n      (layer "F.Fab")\n      (uuid "{_u()}")\n'
                 f'      (effects (font (size 0.6 0.6) (thickness 0.1)))\n    )',
                 f'    (property "Footprint" "etch:{fp.name}"\n      (at 0 0 {c.rot})\n      (layer "F.Fab")\n      (hide yes)\n      (uuid "{_u()}")\n      (effects (font (size 1 1) (thickness 0.15)))\n    )',
                 f'    (property "Datasheet" ""\n      (at 0 0 {c.rot})\n      (layer "F.Fab")\n      (hide yes)\n      (uuid "{_u()}")\n      (effects (font (size 1 1) (thickness 0.15)))\n    )',
                 f'    (property "Description" "{c.part.description.replace(chr(34), "")}"\n      (at 0 0 {c.rot})\n      (layer "F.Fab")\n      (hide yes)\n      (uuid "{_u()}")\n      (effects (font (size 1 1) (thickness 0.15)))\n    )',
                 f'    (property "LCSC" "{c.part.lcsc}"\n      (at 0 0 {c.rot})\n      (layer "F.Fab")\n      (hide yes)\n      (uuid "{_u()}")\n      (effects (font (size 1 1) (thickness 0.15)))\n    )',
                 f'    (attr {"smd" if smd else "through_hole"}{" exclude_from_pos_files exclude_from_bom" if fp.style == "hole" else ""})']
        for (x1, y1, x2, y2) in fp.silk:
            lines.append(f'    (fp_line\n      (start {_f(x1)} {_f(-y1)})\n      (end {_f(x2)} {_f(-y2)})\n      (stroke (width 0.12) (type solid))\n      (layer "F.SilkS")\n      (uuid "{_u()}")\n    )')
        lines.append(f'    (fp_rect\n      (start {_f(cx)} {_f(-(cy + ch))})\n      (end {_f(cx + cw)} {_f(-cy)})\n      (stroke (width 0.05) (type solid))\n      (fill no)\n      (layer "F.CrtYd")\n      (uuid "{_u()}")\n    )')
        lines.append(f'    (fp_rect\n      (start {_f(-fp.body_w / 2)} {_f(-fp.body_h / 2)})\n      (end {_f(fp.body_w / 2)} {_f(fp.body_h / 2)})\n      (stroke (width 0.1) (type solid))\n      (fill no)\n      (layer "F.Fab")\n      (uuid "{_u()}")\n    )')
        for p in fp.pads:
            net = board.net_of(c.ref, p.num)
            netstr = f'\n      (net {net_ids[net.name]} "{net.name}")' if net else ""
            shape = {"rect": "rect", "roundrect": "roundrect", "circle": "circle", "oval": "oval"}[p.shape]
            rr = "\n      (roundrect_rratio 0.25)" if shape == "roundrect" else ""
            if p.layer == "through":
                if not p.plated:
                    lines.append(f'    (pad "" np_thru_hole circle\n      (at {_f(p.x)} {_f(-p.y)} {c.rot})\n      (size {_f(p.w)} {_f(p.h)})\n      (drill {_f(p.drill)})\n      (layers "*.Cu" "*.Mask")\n      (uuid "{_u()}")\n    )')
                else:
                    lines.append(f'    (pad "{p.num}" thru_hole {shape}\n      (at {_f(p.x)} {_f(-p.y)} {c.rot})\n      (size {_f(p.w)} {_f(p.h)})\n      (drill {_f(p.drill)})\n      (layers "*.Cu" "*.Mask")\n      (remove_unused_layers no){rr}{netstr}\n      (uuid "{_u()}")\n    )')
            else:
                paste = ' "F.Paste"' if fp.style != "hole" else ""
                lines.append(f'    (pad "{p.num}" smd {shape}\n      (at {_f(p.x)} {_f(-p.y)} {c.rot})\n      (size {_f(p.w)} {_f(p.h)})\n      (layers "F.Cu"{paste} "F.Mask"){rr}{netstr}\n      (uuid "{_u()}")\n    )')
        lines.append("  )")
        out.append("\n".join(lines))

    # board outline
    pts = board.outline()
    out.append('  (gr_poly\n    (pts\n' + "\n".join(f"      (xy {_f(x)} {Y(y)})" for x, y in pts) +
               f'\n    )\n    (stroke (width 0.1) (type solid))\n    (fill no)\n    (layer "Edge.Cuts")\n    (uuid "{_u()}")\n  )')
    for t in board.texts:
        out.append(f'  (gr_text "{t["text"]}"\n    (at {_f(t["x"])} {Y(t["y"])} {t.get("rot", 0)})\n    (layer "F.SilkS")\n    (uuid "{_u()}")\n'
                   f'    (effects (font (size {_f(t.get("size", 1))} {_f(t.get("size", 1))}) (thickness {_f(max(0.12, t.get("size", 1) * 0.15))})))\n  )')
    for tr in board.traces:
        nid = net_ids.get(tr.net, 0)
        for i in range(len(tr.points) - 1):
            (x1, y1), (x2, y2) = tr.points[i], tr.points[i + 1]
            out.append(f'  (segment\n    (start {_f(x1)} {Y(y1)})\n    (end {_f(x2)} {Y(y2)})\n    (width {_f(tr.width)})\n    (layer "{tr.layer}")\n    (net {nid})\n    (uuid "{_u()}")\n  )')
    for v in board.vias:
        out.append(f'  (via\n    (at {_f(v.x)} {Y(v.y)})\n    (size {_f(v.diameter)})\n    (drill {_f(v.drill)})\n    (layers "F.Cu" "B.Cu")\n    (net {net_ids.get(v.net, 0)})\n    (uuid "{_u()}")\n  )')
    # GND pour zone on B.Cu
    if board.pour_net in net_ids:
        zpts = [(0.3, 0.3), (board.width - 0.3, 0.3), (board.width - 0.3, board.height - 0.3), (0.3, board.height - 0.3)]
        out.append(f'  (zone\n    (net {net_ids[board.pour_net]})\n    (net_name "{board.pour_net}")\n    (layer "B.Cu")\n    (uuid "{_u()}")\n    (hatch edge 0.5)\n'
                   f'    (priority 0)\n    (connect_pads (clearance {_f(board.pour_clearance)}))\n    (min_thickness 0.25)\n    (filled_areas_thickness no)\n'
                   f'    (fill yes\n      (thermal_gap 0.3)\n      (thermal_bridge_width 0.4)\n    )\n    (polygon\n      (pts\n' +
                   "\n".join(f"        (xy {_f(x)} {Y(y)})" for x, y in zpts) + "\n      )\n    )\n  )")
    for (x0, y0, x1, y1) in keepouts or []:
        out.append(f'  (zone\n    (net 0)\n    (net_name "")\n    (layers "F.Cu" "B.Cu")\n    (uuid "{_u()}")\n    (name "antenna keepout")\n    (hatch edge 0.5)\n'
                   f'    (connect_pads (clearance 0))\n    (min_thickness 0.25)\n    (filled_areas_thickness no)\n'
                   f'    (keepout\n      (tracks not_allowed)\n      (vias not_allowed)\n      (pads allowed)\n      (copperpour not_allowed)\n      (footprints allowed)\n    )\n'
                   f'    (fill\n      (thermal_gap 0.5)\n      (thermal_bridge_width 0.5)\n    )\n    (polygon\n      (pts\n' +
                   "\n".join(f"        (xy {_f(x)} {Y(y)})" for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]) + "\n      )\n    )\n  )")
    out.append(")")
    return "\n".join(out) + "\n"


def write_kicad_pro(board: Board) -> str:
    pro = {
        "board": {
            "3dviewports": [],
            "design_settings": {
                "defaults": {"board_outline_line_width": 0.1, "copper_line_width": 0.2, "silk_line_width": 0.12, "silk_text_size_h": 0.7, "silk_text_size_v": 0.7, "silk_text_thickness": 0.12},
                "rule_severities": {
                    "lib_footprint_issues": "ignore", "lib_footprint_mismatch": "ignore", "silk_over_copper": "ignore", "silk_overlap": "ignore",
                    "text_height": "ignore", "text_thickness": "ignore", "footprint_type_mismatch": "ignore", "missing_courtyard": "ignore",
                    "silk_edge_clearance": "ignore", "footprint_symbol_mismatch": "ignore", "isolated_copper": "warning", "solder_mask_bridge": "ignore",
                    "unconnected_items": "error", "clearance": "error", "track_width": "error", "hole_clearance": "error", "copper_edge_clearance": "error",
                    "courtyards_overlap": "warning", "footprint": "ignore", "starved_thermal": "ignore", "via_dangling": "warning", "track_dangling": "warning",
                    "zone_has_empty_net": "ignore", "invalid_outline": "error", "malformed_courtyard": "ignore", "duplicate_footprints": "ignore",
                    "extra_footprint": "ignore", "missing_footprint": "ignore", "net_conflict": "ignore", "annular_width": "error",
                },
                "rules": {
                    "min_clearance": 0.127, "min_connection": 0.127, "min_copper_edge_clearance": 0.25, "min_hole_clearance": 0.25, "min_hole_to_hole": 0.5,
                    "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 1, "min_silk_clearance": 0.0, "min_text_height": 0.5,
                    "min_text_thickness": 0.08, "min_through_hole_diameter": 0.3, "min_track_width": 0.127, "min_via_annular_width": 0.13,
                    "min_via_diameter": 0.5, "solder_mask_to_copper_clearance": 0.0, "use_height_for_length_calcs": True,
                },
                "track_widths": [0.2, 0.25, 0.4, 0.6], "via_dimensions": [{"diameter": 0.6, "drill": 0.3}], "zones_allow_external_fillets": False,
            },
            "layer_presets": [], "viewports": [],
        },
        "boards": [], "cvpcb": {"equivalence_files": []}, "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{board.name}.kicad_pro", "version": 3},
        "net_settings": {
            "classes": [{"bus_width": 12, "clearance": 0.15, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2, "line_style": 0,
                         "microvia_diameter": 0.3, "microvia_drill": 0.1, "name": "Default", "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647,
                         "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": 0.2, "via_diameter": 0.6, "via_drill": 0.3, "wire_width": 6}],
            "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None, "netclass_patterns": [],
        },
        "pcbnew": {"last_paths": {"gencad": "", "idf": "", "netlist": "", "plot": "", "pos_files": "", "specctra_dsn": "", "step": "", "svg": "", "vrml": ""}, "page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []}, "sheets": [], "text_variables": {},
    }
    return json.dumps(pro, indent=2)


def run_kicad_drc(pcb_path: str) -> dict | None:
    cli = kicad_cli()
    if not cli:
        return None
    rep = pcb_path.replace(".kicad_pcb", "-drc.json")
    try:
        r = subprocess.run([cli, "pcb", "drc", "--refill-zones", "--format", "json", "--severity-all", "--units", "mm", "-o", rep, pcb_path],
                           capture_output=True, text=True, timeout=240)
    except Exception as e:  # noqa
        return {"available": True, "error": str(e)}
    if not os.path.exists(rep):
        return {"available": True, "error": (r.stderr or r.stdout)[-800:]}
    with open(rep) as f:
        data = json.load(f)
    viol = data.get("violations", [])
    unc = data.get("unconnected_items", [])
    errs = [v for v in viol if v.get("severity") == "error"]
    warns = [v for v in viol if v.get("severity") == "warning"]
    summary = {}
    for v in viol:
        summary[v.get("type")] = summary.get(v.get("type"), 0) + 1
    return {"available": True, "drc_passed": len(errs) == 0 and len(unc) == 0, "violations": len(errs), "warnings": len(warns),
            "unconnected": len(unc), "by_type": summary, "report": os.path.basename(rep), "kicad_version": _kicad_version(cli),
            "samples": [{"type": v.get("type"), "severity": v.get("severity"), "description": v.get("description", "")[:160]} for v in (errs + warns)[:12]]}


def _kicad_version(cli: str) -> str:
    try:
        return subprocess.run([cli, "version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return "?"


def kicad_export_gerbers(pcb_path: str, out_dir: str) -> list[str]:
    cli = kicad_cli()
    if not cli:
        return []
    os.makedirs(out_dir, exist_ok=True)
    try:
        subprocess.run([cli, "pcb", "export", "gerbers", "--layers", "F.Cu,B.Cu,F.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts",
                        "--subtract-soldermask", "--no-protel-ext", "-o", out_dir + "/", pcb_path], capture_output=True, text=True, timeout=240)
        subprocess.run([cli, "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2",
                        "-o", out_dir + "/", pcb_path], capture_output=True, text=True, timeout=240)
    except Exception:
        pass
    return sorted(os.listdir(out_dir))


def kicad_render_png(pcb_path: str, out_png: str, side: str = "top") -> bool:
    cli = kicad_cli()
    if not cli:
        return False
    try:
        r = subprocess.run([cli, "pcb", "render", "--side", side, "--background", "opaque", "--quality", "high", "--zoom", "1.1",
                            "--width", "1600", "--height", "1100", "-o", out_png, pcb_path], capture_output=True, text=True, timeout=300)
        return os.path.exists(out_png)
    except Exception:
        return False
