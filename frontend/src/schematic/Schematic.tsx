import { useEffect, useMemo, useRef, useState } from 'react'
import ELK, { type ElkNode, type ElkExtendedEdge, type ElkPort } from 'elkjs/lib/elk.bundled.js'
import { useStore } from '../store'
import type { Component, Net } from '../protocol'
import { catColor } from '../util/format'

const elk = new ELK()
const PIN_PITCH = 14
const CHAR_W = 6.2

interface LNode { id: string; x: number; y: number; w: number; h: number; comp: Component; ports: { id: string; x: number; y: number; side: 'WEST' | 'EAST'; name: string; net?: string; netCls?: string }[] }
interface LEdge { id: string; net: string; cls: string; points: { x: number; y: number }[] }
interface Layout { nodes: LNode[]; edges: LEdge[]; w: number; h: number }

const isLeft = (t: string) => t === 'power_in' || t === 'input' || t === 'gnd'
const WIRE_NETS = new Set(['signal', 'highspeed', 'analog'])

function buildGraph(components: Component[], nets: Net[]) {
  const pinNet = new Map<string, Net>()
  for (const n of nets) for (const p of n.pins) pinNet.set(p, n)
  const nodes: ElkNode[] = []
  const meta = new Map<string, { comp: Component; ports: LNode['ports'] }>()
  for (const c of components) {
    if (c.body.style === 'hole' || c.category === 'mechanical') continue
    // connected pins only (plus keep at least 2)
    let pins = c.pins.filter(p => pinNet.has(`${c.ref}.${p.num}`))
    if (pins.length === 0) pins = c.pins.slice(0, 2)
    const isPassive = c.category === 'passive' || c.category === 'led' || c.category === 'switch' || c.category === 'crystal'
    const left = pins.filter((p, i) => isPassive ? i % 2 === 0 : isLeft(p.type) || (p.type === 'passive' && i % 2 === 0) || (p.type === 'bidirectional' && i % 2 === 0))
    const right = pins.filter(p => !left.includes(p))
    const rows = Math.max(left.length, right.length, 1)
    const nameW = Math.max(c.name.length, (c.value || '').length, 8) * CHAR_W + 24
    const pinW = Math.max(...pins.map(p => p.name.length), 3) * CHAR_W
    const w = Math.max(nameW, pinW * 2 + 30)
    const h = rows * PIN_PITCH + 34
    const ports: LNode['ports'] = []
    const elkPorts: ElkPort[] = []
    left.forEach((p, i) => { const id = `${c.ref}.${p.num}`; const net = pinNet.get(id); ports.push({ id, x: 0, y: 26 + i * PIN_PITCH, side: 'WEST', name: p.name, net: net?.name, netCls: net?.cls }); elkPorts.push({ id, width: 1, height: 1, layoutOptions: { 'elk.port.side': 'WEST' } }) })
    right.forEach((p, i) => { const id = `${c.ref}.${p.num}`; const net = pinNet.get(id); ports.push({ id, x: w, y: 26 + i * PIN_PITCH, side: 'EAST', name: p.name, net: net?.name, netCls: net?.cls }); elkPorts.push({ id, width: 1, height: 1, layoutOptions: { 'elk.port.side': 'EAST' } }) })
    nodes.push({ id: c.ref, width: w, height: h, ports: elkPorts, layoutOptions: { 'elk.portConstraints': 'FIXED_SIDE', 'elk.portAlignment.default': 'DISTRIBUTED', 'elk.spacing.portPort': String(PIN_PITCH - 1) } })
    meta.set(c.ref, { comp: c, ports })
  }
  const edges: ElkExtendedEdge[] = []
  const edgeMeta = new Map<string, { net: string; cls: string }>()
  const present = new Set(nodes.map(n => n.id))
  for (const n of nets) {
    const wire = WIRE_NETS.has(n.cls) || (n.cls === 'power' && n.pins.length <= 3)
    if (!wire) continue
    const pins = n.pins.filter(p => present.has(p.split('.')[0]))
    if (pins.length < 2) continue
    // star from the first pin; with mergeEdges ELK shares the segments leaving the source port (bus-like)
    for (let i = 1; i < pins.length; i++) {
      const id = `${n.name}#${i}`
      edges.push({ id, sources: [pins[0]], targets: [pins[i]] })
      edgeMeta.set(id, { net: n.name, cls: n.cls })
    }
  }
  const graph: ElkNode = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.edgeRouting': 'ORTHOGONAL',
      'elk.spacing.nodeNode': '28', 'elk.layered.spacing.nodeNodeBetweenLayers': '56', 'elk.layered.spacing.edgeNodeBetweenLayers': '22',
      'elk.spacing.edgeEdge': '12', 'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX', 'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP', 'elk.layered.mergeEdges': 'true',
      'elk.padding': '[top=24,left=60,bottom=24,right=60]',
    },
    children: nodes, edges,
  }
  return { graph, meta, edgeMeta }
}

export function Schematic() {
  const components = useStore(s => s.components)
  const nets = useStore(s => s.nets)
  const hoverNet = useStore(s => s.hoverNet); const setHoverNet = useStore(s => s.setHoverNet)
  const [layout, setLayout] = useState<Layout | null>(null)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const fitted = useRef(false)

  const key = useMemo(() => components.map(c => c.ref).join(',') + '|' + nets.map(n => n.name + n.pins.length).join(','), [components, nets])
  useEffect(() => {
    if (!components.length) { setLayout(null); return }
    let cancelled = false
    const { graph, meta, edgeMeta } = buildGraph(components, nets)
    elk.layout(graph).then(res => {
      if (cancelled) return
      const nodes: LNode[] = (res.children ?? []).map(n => {
        const m = meta.get(n.id)!
        // take ELK's crossing-minimised port order/positions
        const byId = new Map((n.ports ?? []).map(p => [p.id, p]))
        const ports = m.ports.map(p => { const ep = byId.get(p.id); return ep ? { ...p, y: (ep.y ?? 0) + 0.5, x: p.side === 'WEST' ? 0 : (n.width ?? 0) } : p })
        return { id: n.id, x: n.x ?? 0, y: n.y ?? 0, w: n.width ?? 0, h: n.height ?? 0, comp: m.comp, ports }
      })
      const edges: LEdge[] = (res.edges ?? []).flatMap(e => {
        const em = edgeMeta.get(e.id)!
        return (e.sections ?? []).map((sec, i) => ({ id: `${e.id}/${i}`, net: em.net, cls: em.cls, points: [sec.startPoint, ...(sec.bendPoints ?? []), sec.endPoint] }))
      })
      setLayout({ nodes, edges, w: res.width ?? 800, h: res.height ?? 600 })
    }).catch(err => console.warn('elk failed', err))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  // fit on first layout
  useEffect(() => {
    if (!layout || !wrap.current) return
    const r = wrap.current.getBoundingClientRect()
    const k = Math.min(r.width / (layout.w + 20), r.height / (layout.h + 20), 2.2)
    setView({ k, x: (r.width - layout.w * k) / 2, y: (r.height - layout.h * k) / 2 })
    fitted.current = true
  }, [layout])

  const onWheel = (e: React.WheelEvent) => {
    const r = wrap.current!.getBoundingClientRect()
    const mx = e.clientX - r.left, my = e.clientY - r.top
    const f = Math.exp(-e.deltaY * 0.0015)
    setView(v => { const k = Math.min(6, Math.max(0.15, v.k * f)); const s = k / v.k; return { k, x: mx - (mx - v.x) * s, y: my - (my - v.y) * s } })
  }
  const onDown = (e: React.MouseEvent) => { drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y } }
  const onMove = (e: React.MouseEvent) => { const d = drag.current; if (!d) return; setView(v => ({ ...v, x: d.vx + (e.clientX - d.x), y: d.vy + (e.clientY - d.y) })) }
  const onUp = () => { drag.current = null }

  if (!layout) return <div ref={wrap} className="schem" style={{ display: 'grid', placeItems: 'center' }}><div className="empty">{components.length ? 'laying out schematic…' : 'waiting for components…'}</div></div>

  const netColor = (cls: string, net: string) => hoverNet === net ? '#ffffff' : cls === 'power' ? '#e8a35c' : cls === 'highspeed' ? '#b48cff' : cls === 'analog' ? '#7cff5a' : '#3ee7ff'

  return (
    <div ref={wrap} className="schem" onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
      <svg>
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <pattern id="sgrid" width="20" height="20" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.8" fill="rgba(215,222,232,0.10)" /></pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#sgrid)" />
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {/* wires */}
          {layout.edges.map((e, i) => {
            const d = e.points.map((p, j) => `${j ? 'L' : 'M'}${p.x},${p.y}`).join(' ')
            const hot = hoverNet === e.net
            return (
              <g key={e.id} onMouseEnter={() => setHoverNet(e.net)} onMouseLeave={() => setHoverNet(null)} style={{ cursor: 'pointer' }}>
                <path d={d} fill="none" stroke="transparent" strokeWidth={10} />
                <path d={d} fill="none" stroke={netColor(e.cls, e.net)} strokeWidth={hot ? 2.6 : e.cls === 'power' ? 2.2 : 1.4} strokeLinejoin="round" filter={hot ? 'url(#glow)' : undefined}
                  style={{ strokeDasharray: 2000, strokeDashoffset: 2000, animation: `wire 0.9s ${0.4 + i * 0.05}s ease-out forwards` }} />
                {e.points.length > 0 && [e.points[0], e.points[e.points.length - 1]].map((p, j) => <circle key={j} cx={p.x} cy={p.y} r={2} fill={netColor(e.cls, e.net)} />)}
                {hot && <text x={e.points[0].x + 4} y={e.points[0].y - 4} fill="#fff" fontSize={9} fontFamily="JetBrains Mono">{e.net}</text>}
              </g>
            )
          })}
          {/* nodes */}
          {layout.nodes.map((n, i) => {
            const col = catColor(n.comp.category)
            return (
              <g key={n.id} transform={`translate(${n.x},${n.y})`} style={{ animation: `nodeIn 0.5s ${i * 0.04}s cubic-bezier(.2,.8,.2,1) both`, transformOrigin: `${n.x + n.w / 2}px ${n.y + n.h / 2}px` }}>
                <rect width={n.w} height={n.h} rx={3} fill="rgba(13,17,23,0.92)" stroke={col} strokeOpacity={0.7} strokeWidth={1.2} />
                <rect width={n.w} height={18} rx={3} fill={col} fillOpacity={0.12} />
                <text x={6} y={12.5} fill={col} fontSize={10} fontWeight={700} fontFamily="JetBrains Mono">{n.id}</text>
                <text x={n.w - 6} y={12.5} fill="#d7dee8" fontSize={8.5} textAnchor="end" fontFamily="JetBrains Mono">{n.comp.name.slice(0, 22)}</text>
                {n.comp.value && <text x={n.w / 2} y={n.h - 6} fill="#e8a35c" fontSize={8.5} textAnchor="middle" fontFamily="JetBrains Mono">{n.comp.value}</text>}
                {n.ports.map(p => {
                  const west = p.side === 'WEST'
                  const labelNet = p.net && !layout.edges.some(e => e.net === p.net)
                  const isGnd = p.netCls === 'gnd'
                  const isPwr = p.netCls === 'power'
                  const hot = hoverNet != null && hoverNet === p.net
                  return (
                    <g key={p.id} onMouseEnter={() => p.net && setHoverNet(p.net)} onMouseLeave={() => setHoverNet(null)}>
                      <line x1={west ? 0 : n.w} y1={p.y} x2={west ? -10 : n.w + 10} y2={p.y} stroke={hot ? '#fff' : '#9aa7b8'} strokeWidth={1.2} />
                      <text x={west ? 5 : n.w - 5} y={p.y + 3} fill={hot ? '#fff' : '#b9c3d0'} fontSize={7.5} textAnchor={west ? 'start' : 'end'} fontFamily="JetBrains Mono">{p.name}</text>
                      {labelNet && isGnd && (
                        <g transform={`translate(${west ? -10 : n.w + 10},${p.y})`}>
                          <line x1={0} y1={0} x2={0} y2={8} stroke="#7cff5a" strokeWidth={1.2} />
                          <line x1={-5} y1={8} x2={5} y2={8} stroke="#7cff5a" strokeWidth={1.4} /><line x1={-3} y1={10.5} x2={3} y2={10.5} stroke="#7cff5a" strokeWidth={1.2} /><line x1={-1} y1={13} x2={1} y2={13} stroke="#7cff5a" strokeWidth={1.2} />
                        </g>
                      )}
                      {labelNet && !isGnd && (
                        <g transform={`translate(${west ? -10 : n.w + 10},${p.y})`}>
                          <line x1={0} y1={0} x2={0} y2={-8} stroke={isPwr ? '#e8a35c' : '#3ee7ff'} strokeWidth={1.2} />
                          <path d={west ? `M0,-8 L-${(p.net!.length * 5.2 + 8)},-8 L-${(p.net!.length * 5.2 + 12)},-13 L-${(p.net!.length * 5.2 + 8)},-18 L0,-18 Z` : `M0,-8 L${(p.net!.length * 5.2 + 8)},-8 L${(p.net!.length * 5.2 + 12)},-13 L${(p.net!.length * 5.2 + 8)},-18 L0,-18 Z`} fill={isPwr ? 'rgba(232,163,92,0.15)' : 'rgba(62,231,255,0.12)'} stroke={isPwr ? '#e8a35c' : '#3ee7ff'} strokeWidth={1} />
                          <text x={west ? -4 : 4} y={-10.5} fill={isPwr ? '#ffb86b' : '#3ee7ff'} fontSize={7.5} textAnchor={west ? 'end' : 'start'} fontFamily="JetBrains Mono" fontWeight={600}>{p.net}</text>
                        </g>
                      )}
                    </g>
                  )
                })}
              </g>
            )
          })}
        </g>
      </svg>
      <div className="schem-hint">{layout.nodes.length} SYMBOLS · {layout.edges.length} WIRES · {nets.length} NETS · wheel to zoom, drag to pan, hover a wire</div>
      <style>{`@keyframes wire{to{stroke-dashoffset:0}} @keyframes nodeIn{from{opacity:0;transform:translateY(12px) scale(.96)}to{opacity:1}}`}</style>
    </div>
  )
}
