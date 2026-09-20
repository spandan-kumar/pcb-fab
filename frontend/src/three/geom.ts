import * as THREE from 'three'

/** Flat polyline → triangle mesh with round joints, in the XY plane at z=0. Vertices are emitted in path order. */
export function polylineGeometry(points: number[][], width: number, segs = 10): THREE.BufferGeometry {
  const pos: number[] = []
  const hw = width / 2
  const disc = (cx: number, cy: number) => {
    for (let i = 0; i < segs; i++) {
      const a0 = (i / segs) * Math.PI * 2, a1 = ((i + 1) / segs) * Math.PI * 2
      pos.push(cx, cy, 0, cx + Math.cos(a0) * hw, cy + Math.sin(a0) * hw, 0, cx + Math.cos(a1) * hw, cy + Math.sin(a1) * hw, 0)
    }
  }
  if (points.length === 0) return new THREE.BufferGeometry()
  disc(points[0][0], points[0][1])
  for (let i = 1; i < points.length; i++) {
    const [ax, ay] = points[i - 1], [bx, by] = points[i]
    const dx = bx - ax, dy = by - ay, L = Math.hypot(dx, dy)
    if (L > 1e-6) {
      const nx = (-dy / L) * hw, ny = (dx / L) * hw
      pos.push(ax + nx, ay + ny, 0, ax - nx, ay - ny, 0, bx + nx, by + ny, 0)
      pos.push(ax - nx, ay - ny, 0, bx - nx, by - ny, 0, bx + nx, by + ny, 0)
    }
    disc(bx, by)
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  const n = pos.length / 3
  const normals = new Float32Array(n * 3)
  for (let i = 0; i < n; i++) normals[i * 3 + 2] = 1
  g.setAttribute('normal', new THREE.BufferAttribute(normals, 3))
  return g
}

export function pathLength(points: number[][]) {
  let L = 0
  for (let i = 1; i < points.length; i++) L += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
  return L
}
export function pointAt(points: number[][], frac: number): [number, number] {
  const total = pathLength(points)
  let d = frac * total
  for (let i = 1; i < points.length; i++) {
    const L = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
    if (d <= L) { const k = L ? d / L : 0; return [points[i - 1][0] + (points[i][0] - points[i - 1][0]) * k, points[i - 1][1] + (points[i][1] - points[i - 1][1]) * k] }
    d -= L
  }
  const p = points[points.length - 1]; return [p[0], p[1]]
}

export function roundedRectShape(w: number, h: number, r: number, x0 = 0, y0 = 0): THREE.Shape {
  const s = new THREE.Shape()
  const rr = Math.min(r, w / 2, h / 2)
  s.moveTo(x0 + rr, y0)
  s.lineTo(x0 + w - rr, y0); s.absarc(x0 + w - rr, y0 + rr, rr, -Math.PI / 2, 0, false)
  s.lineTo(x0 + w, y0 + h - rr); s.absarc(x0 + w - rr, y0 + h - rr, rr, 0, Math.PI / 2, false)
  s.lineTo(x0 + rr, y0 + h); s.absarc(x0 + rr, y0 + h - rr, rr, Math.PI / 2, Math.PI, false)
  s.lineTo(x0, y0 + rr); s.absarc(x0 + rr, y0 + rr, rr, Math.PI, Math.PI * 1.5, false)
  return s
}

export function outlineShape(outline: number[][], w: number, h: number, r: number): THREE.Shape {
  // If the outline is a plain 4-point rectangle use the rounded version; otherwise follow the polygon.
  if (outline.length === 4 && r > 0) return roundedRectShape(w, h, r)
  const s = new THREE.Shape()
  outline.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)))
  s.closePath()
  return s
}

export function circlePath(x: number, y: number, r: number): THREE.Path {
  const p = new THREE.Path(); p.absarc(x, y, r, 0, Math.PI * 2, true); return p
}

/** Merge geometries sharing the same attributes (position/normal) into one. */
export function mergeGeoms(geoms: THREE.BufferGeometry[]): THREE.BufferGeometry {
  const pos: number[] = [], nor: number[] = []
  for (const g of geoms) {
    const ng = g.index ? g.toNonIndexed() : g
    const p = ng.getAttribute('position'); let n = ng.getAttribute('normal')
    if (!n) { ng.computeVertexNormals(); n = ng.getAttribute('normal') }
    for (let i = 0; i < p.count; i++) { pos.push(p.getX(i), p.getY(i), p.getZ(i)); nor.push(n.getX(i), n.getY(i), n.getZ(i)) }
    if (ng !== g) ng.dispose()
  }
  const out = new THREE.BufferGeometry()
  out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  out.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  return out
}

/** A pad as a thin 3D geometry positioned at (x,y), rotated `rot` degrees. */
export function padGeometry(shape: string, x: number, y: number, w: number, h: number, thick: number, z: number): THREE.BufferGeometry {
  let g: THREE.BufferGeometry
  if (shape === 'circle') { g = new THREE.CylinderGeometry(w / 2, w / 2, thick, 20); g.rotateX(Math.PI / 2) }
  else if (shape === 'oval' || shape === 'roundrect') {
    const r = shape === 'oval' ? Math.min(w, h) / 2 : Math.min(w, h) * 0.25
    const s = roundedRectShape(w, h, r, -w / 2, -h / 2)
    g = new THREE.ExtrudeGeometry(s, { depth: thick, bevelEnabled: false, curveSegments: 6 }); g.translate(0, 0, -thick / 2)
  } else g = new THREE.BoxGeometry(w, h, thick)
  g.translate(x, y, z)
  return g
}
