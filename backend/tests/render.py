"""Quick PNG render of a Board for debugging: uv run python -m tests.render <events.json|-> out.png"""
from PIL import Image, ImageDraw
from etch.model import Board, rotate

def render(b: Board, path: str, scale=16, blocked=None):
    W, H = int(b.width * scale) + 1, int(b.height * scale) + 1
    im = Image.new("RGB", (W, H), (20, 40, 25))
    d = ImageDraw.Draw(im)
    T = lambda x, y: (x * scale, H - y * scale)
    for t in b.traces:
        col = (200, 120, 60) if t.layer == "F.Cu" else (60, 100, 200)
        pts = [T(x, y) for x, y in t.points]
        d.line(pts, fill=col, width=max(1, int(t.width * scale)), joint="curve")
    for c in b.components:
        for p in c.footprint.pads:
            cx, cy, w, h = c.pad_abs(p)
            x0, y0 = T(cx - w / 2, cy + h / 2); x1, y1 = T(cx + w / 2, cy - h / 2)
            d.rectangle([x0, y0, x1, y1], fill=(230, 200, 90) if p.layer != "through" else (240, 240, 200))
        bx, by, bw, bh = c.courtyard_abs()
        d.rectangle([*T(bx, by + bh), *T(bx + bw, by)], outline=(90, 90, 90))
        d.text(T(bx, by + bh), c.ref, fill=(255, 255, 255))
    for v in b.vias:
        x, y = T(v.x, v.y); r = v.diameter / 2 * scale
        d.ellipse([x - r, y - r, x + r, y + r], fill=(180, 180, 180), outline=(0, 0, 0))
    im.save(path)
