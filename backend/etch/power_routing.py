"""Current-class trace widths and explicit reporting of constrained power paths.

The existing Net.width policy is a routing target, not an ampacity calculation.
Narrow pad escapes are permitted locally; narrow trunks remain review warnings.
"""
from __future__ import annotations

import math

from .drc import RULES, Item, collect_items, distance, _pt_rect, _seg_seg
from .footprints import ANT_H
from .model import Board, Net, Trace, rotate

NECK_REACH = 1.0  # permitted distance outside a small pad, mm
WIDTH_STEP = 0.2  # geometry sampling length, mm (independent of routing grid)


def _segments(trace: Trace):
    for a, b in zip(trace.points, trace.points[1:]):
        n = max(1, math.ceil(math.dist(a, b) / WIDTH_STEP))
        for i in range(n):
            yield tuple(a[j] + (b[j] - a[j]) * i / n for j in (0, 1)), \
                tuple(a[j] + (b[j] - a[j]) * (i + 1) / n for j in (0, 1))


def _pads(board: Board, net: Net):
    for ref, num in net.pins:
        c = board.comp(ref)
        pad = c.pad(num) if c else None
        if pad is None:
            continue
        x, y, w, h = c.pad_abs(pad)
        limit = 0.2 if min(w, h) < 0.7 else max(0.2, min(w, h) - 0.02)
        if limit < net.width:
            yield (x - w / 2, y - h / 2, x + w / 2, y + h / 2), pad.layer, limit


def widen_traces(board: Board, net: Net, traces: list[Trace], reserved: list[Item] | None = None) -> list[Trace]:
    """Grow copper only where exact geometry preserves design clearance.

    Never shrink or move existing copper. Adjacent equal-width spans are merged
    so the UI and both exporters receive the same variable-width path.
    """
    clearance = RULES['design_clearance_mm']
    obstacles = [it for it in collect_items(board) if it.net != net.name] + (reserved or [])
    for c in board.components:
        for pad in c.footprint.pads:
            if pad.layer == 'through' and not pad.plated:
                x, y, _, _ = c.pad_abs(pad)
                for layer in ('F.Cu', 'B.Cu'):
                    obstacles.append(Item('circle', '', layer, 'hole', (x, y),
                                          pad.drill / 2 + RULES['hole_to_copper_mm'] - clearance))
        fp = c.footprint
        if fp.style == 'module' and fp.edge == '+y':
            a = rotate(-fp.body_w / 2, fp.body_h / 2 - ANT_H, c.rot)
            b = rotate(fp.body_w / 2, fp.body_h / 2, c.rot)
            rect = (c.x + min(a[0], b[0]), c.y + min(a[1], b[1]),
                    c.x + max(a[0], b[0]), c.y + max(a[1], b[1]))
            for layer in ('F.Cu', 'B.Cu'):
                obstacles.append(Item('rect', '', layer, 'antenna', rect, 0))
    # Short segments need only nearby obstacles, not every item on the board.
    index = {}
    for i, it in enumerate(obstacles):
        x0, y0, x1, y1 = it.bbox
        for x in range(math.floor(x0 / 2), math.floor(x1 / 2) + 1):
            for y in range(math.floor(y0 / 2), math.floor(y1 / 2) + 1):
                index.setdefault((it.layer, x, y), set()).add(i)
    pads = list(_pads(board, net))
    outline = board.outline()
    edges = [(*a, *b) for a, b in zip(outline, outline[1:] + outline[:1])]
    result = []
    for trace in traces:
        current = None
        for a, b in _segments(trace):
            line = Item('seg', net.name, trace.layer, '', (*a, *b), 0)
            reach = net.width / 2 + clearance
            x0, y0, x1, y1 = line.bbox
            nearby = set()
            for x in range(math.floor((x0 - reach) / 2), math.floor((x1 + reach) / 2) + 1):
                for y in range(math.floor((y0 - reach) / 2), math.floor((y1 + reach) / 2) + 1):
                    nearby.update(index.get((trace.layer, x, y), ()))
            radius = min([net.width / 2] + [distance(line, obstacles[i]) - clearance for i in nearby]
                         + [_seg_seg(line.a, edge) - RULES['edge_clearance_mm'] for edge in edges])
            # Keep fixed fine-pitch escapes narrow until clear of the pad.
            for rect, layer, limit in pads:
                if layer == 'through' or trace.layer == 'F.Cu':
                    pad_item = Item('rect', net.name, trace.layer, '', rect, 0)
                    if distance(line, pad_item) < 0.4:
                        radius = min(radius, limit / 2)
            widths = [trace.width, 0.25, 0.4, 0.6, net.width]
            width = max([trace.width] + [w for w in widths if trace.width <= w <= net.width and w / 2 <= radius + 1e-7])
            if current is not None and current.width == width:
                # Only drop truly collinear middle points; keep all corners.
                p, q = current.points[-2:]
                if abs((q[0] - p[0]) * (b[1] - q[1]) - (q[1] - p[1]) * (b[0] - q[0])) < 1e-9 \
                        and (q[0] - p[0]) * (b[0] - q[0]) + (q[1] - p[1]) * (b[1] - q[1]) >= 0:
                    current.points[-1] = b
                else:
                    current.points.append(b)
            else:
                current = Trace(net.name, trace.layer, width, [a, b])
                result.append(current)
    return result


def width_summary(board: Board, net: Net) -> dict:
    """Measure narrow copper outside the allowed small-pad neighbourhoods."""
    pads = list(_pads(board, net))
    narrow = neck = length = 0.0
    for trace in board.traces:
        if trace.net != net.name:
            continue
        length += trace.length
        if trace.width >= net.width - 1e-6:
            continue
        for a, b in _segments(trace):
            span = math.dist(a, b)
            if any((layer == 'through' or trace.layer == 'F.Cu')
                   and max(_pt_rect(*a, *rect), _pt_rect(*b, *rect)) <= NECK_REACH + 1e-6
                   for rect, layer, _ in pads):
                neck += span
            else:
                narrow += span
    return {'target_width_mm': net.width, 'neckdown_mm': round(neck, 2), 'constrained_mm': round(narrow, 2),
            'width_ok': length > 1e-6 and narrow < 1e-6}
