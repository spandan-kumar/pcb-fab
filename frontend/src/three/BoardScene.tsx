import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Environment, Lightformer } from '@react-three/drei'
import { Label } from './Label'
import { Effects } from './Effects'
import { useStore } from '../store'
import { live } from '../live'
import type { Board, Component, Drc, Footprint, MaskColor, ThermalFrame, Trace, Via } from '../protocol'
import * as M from './materials'
import { circlePath, mergeGeoms, outlineShape, padGeometry, pathLength, pointAt, polylineGeometry, roundedRectShape } from './geom'
import { turbo } from '../util/colormap'
const Q = new URLSearchParams(location.search)
const NOFX = Q.has('nofx')
const flag = (n: string) => Q.has(n)
const T = 1.6 // board thickness
const CU = 0.035
const Z_TOP = T + CU / 2
const Z_BOT = -CU / 2

// explode offsets per layer (multiplied by explode factor)
const EX = { parts: 30, silk: 22, mask: 16, fcu: 10, board: 0, bcu: -10, drill: -16, edge: -22 }

interface SceneData {
  board: Board
  components: Component[]
  traces: Trace[]
  vias: Via[]
  pour: { clearance: number; net: string } | null
  color: MaskColor
  ratsnest: [number, number, number, number, string][]
  routedNets: string[]
  failedNets: string[]
  drc: Drc | null
  thermal: ThermalFrame | null
  positions: Record<string, [number, number, number]>
  nets: { name: string; pins: string[]; cls: string }[]
  live: boolean
}

/* ------------------------------------------------------------------ */
export function BoardScene({ decor }: { decor?: boolean }) {
  return (
    <Canvas dpr={[1, 1.75]} gl={{ antialias: true, powerPreference: 'high-performance', preserveDrawingBuffer: true }} camera={{ fov: 32, near: 0.5, far: 2000, position: [-30, -60, 60], up: [0, 0, 1] }}>
      <color attach="background" args={['#07090c']} />
      {!flag('nofog') && <fog attach="fog" args={['#07090c', 160, 420]} />}
      <ambientLight intensity={0.35} />
      <hemisphereLight args={['#dfe7ff', '#2a1d10', 0.55]} up={new THREE.Vector3(0, 0, 1)} />
      <directionalLight position={[40, -60, 90]} intensity={1.6} color="#fff3e0" />
      <directionalLight position={[-60, 40, 40]} intensity={0.5} color="#9fd8ff" />
      {!flag('noenv') && <Environment resolution={128}>
        <Lightformer intensity={2} position={[0, -20, 30]} rotation-x={Math.PI / 2} scale={[40, 40, 1]} color="#fff2dd" />
        <Lightformer intensity={0.8} position={[40, 30, 20]} rotation-x={Math.PI / 2} scale={[30, 20, 1]} color="#8fd7ff" />
        <Lightformer intensity={0.6} position={[-40, 20, 10]} rotation-x={Math.PI / 2} scale={[20, 20, 1]} color="#ffb86b" />
      </Environment>}
      <DebugHook />
      {flag('simple') ? <mesh position={[0, 0, 0]}><boxGeometry args={[20, 12, 2]} /><meshStandardMaterial color="#1d5c2b" /></mesh> : decor ? <DecorBoard /> : <LiveBoard />}
      {!NOFX && <Effects />}
    </Canvas>
  )
}

function DebugHook() {
  const st = useThree()
  useEffect(() => { (window as unknown as { __r3f: unknown }).__r3f = st }, [st])
  return null
}

/* ------------------------------------------------------------------ */
function LiveBoard() {
  const board = useStore(s => s.board)
  const components = useStore(s => s.components)
  const traces = useStore(s => s.traces)
  const vias = useStore(s => s.vias)
  const pour = useStore(s => s.pour)
  const color = useStore(s => s.color)
  const ratsnest = useStore(s => s.ratsnest)
  const routedNets = useStore(s => s.routedNets)
  const failedNets = useStore(s => s.failedNets)
  const drc = useStore(s => s.drc)
  const thermal = useStore(s => s.thermal)
  const positions = useStore(s => s.positions)
  const nets = useStore(s => s.nets)
  if (!board) return flag('nowait') ? null : <WaitingBoard />
  const data: SceneData = { board, components, traces, vias, pour, color, ratsnest, routedNets, failedNets, drc, thermal, positions, nets, live: true }
  return <BoardContent data={data} />
}

function WaitingBoard() {
  // A placeholder blank board while the agent thinks
  const ref = useRef<THREE.Group>(null)
  useFrame(({ clock }) => { if (ref.current) ref.current.rotation.z = Math.sin(clock.elapsedTime * 0.3) * 0.15 })
  const geo = useMemo(() => new THREE.ExtrudeGeometry(roundedRectShape(50, 36, 2, -25, -18), { depth: T, bevelEnabled: false }), [])
  return (
    <group ref={ref} position={[0, 0, 0]}>
      <CameraRig center={[0, 0]} size={50} decor={false} />
      <mesh geometry={geo}><meshStandardMaterial color="#14161a" roughness={0.5} metalness={0.2} transparent opacity={0.6} wireframe /></mesh>
      <Label position={[0, 0, 3]} size={2.2} color="#3ee7ff" text="AWAITING ARCHITECTURE" />
    </group>
  )
}

/* ------------------------------------------------------------------ */
function BoardContent({ data }: { data: SceneData }) {
  const { board } = data
  const tab = useStore(s => s.tab)
  const exploded = useStore(s => s.exploded)
  const layerVis = useStore(s => s.layerVis)
  const hoverNet = useStore(s => s.hoverNet)
  const selected = useStore(s => s.selectedViolation)
  const ex = useRef(0)
  const gParts = useRef<THREE.Group>(null), gSilk = useRef<THREE.Group>(null), gMask = useRef<THREE.Group>(null), gFcu = useRef<THREE.Group>(null), gBcu = useRef<THREE.Group>(null), gDrill = useRef<THREE.Group>(null), gEdge = useRef<THREE.Group>(null), gLabels = useRef<THREE.Group>(null)

  useFrame((_, dt) => {
    const target = exploded && data.live ? 1 : 0
    ex.current += (target - ex.current) * Math.min(1, dt * 4)
    const e = ex.current
    if (gParts.current) gParts.current.position.z = e * EX.parts
    if (gSilk.current) gSilk.current.position.z = e * EX.silk
    if (gMask.current) { gMask.current.position.z = e * EX.mask; gMask.current.visible = e > 0.02 }
    if (gFcu.current) gFcu.current.position.z = e * EX.fcu
    if (gBcu.current) gBcu.current.position.z = e * EX.bcu
    if (gDrill.current) { gDrill.current.position.z = e * EX.drill; gDrill.current.visible = e > 0.02 }
    if (gEdge.current) { gEdge.current.position.z = e * EX.edge; gEdge.current.visible = e > 0.02 }
    if (gLabels.current) gLabels.current.visible = e > 0.5
    // component transparency in thermal view (opacity only; `transparent` flag is toggled in an effect so the shader recompiles)
    const op = tab === 'thermal' && data.live ? 0.22 : 1
    for (const m of M.ALL_BODY_MATS) {
      const cur = m.opacity
      const nx = cur + (op - cur) * Math.min(1, dt * 6)
      if (Math.abs(nx - cur) > 0.0005) { m.opacity = nx; m.depthWrite = nx > 0.5 }
    }
  })

  useEffect(() => {
    const t = tab === 'thermal' && data.live
    for (const m of M.ALL_BODY_MATS) { if (m.transparent !== t) { m.transparent = t; m.needsUpdate = true } }
  }, [tab, data.live])

  const vis = (l: string) => !exploded || layerVis[l] !== false
  const topTraces = data.traces.filter(t => t.layer === 'F.Cu')
  const botTraces = data.traces.filter(t => t.layer !== 'F.Cu')

  return (
    <group>
      {!flag('nocam') && <CameraRig center={[board.width / 2, board.height / 2]} size={Math.max(board.width, board.height)} decor={!data.live} />}
      {!flag('nosub') && <Substrate board={board} color={data.color} />}
      {!flag('noshadow') && <ShadowBlob board={board} />}
      {/* edge cuts (exploded only) */}
      {!flag('noedge') && <group ref={gEdge}><EdgeCuts board={board} /></group>}
      {!flag('nomask') && <group ref={gMask}><MaskGhost board={board} color={data.color} /></group>}
      {!flag('nodrill') && <group ref={gDrill}><DrillHits board={board} vias={data.vias} positions={data.positions} /></group>}
      <group ref={gFcu} visible={vis('F.Cu')}>
        {!flag('notraces') && topTraces.map((t, i) => <TraceMesh key={i} trace={t} z={Z_TOP} hovered={hoverNet === t.net} />)}
        {!flag('nopads') && <PadsLayer board={board} live={data.live} positions={data.positions} />}
      </group>
      <group ref={gBcu} visible={vis('B.Cu')}>
        {!flag('nopour') && data.pour && <Pour board={board} color={data.color} traces={botTraces} vias={data.vias} clearance={data.pour.clearance} gndNet={data.pour.net} positions={data.positions} />}
        {botTraces.map((t, i) => <TraceMesh key={i} trace={t} z={data.pour ? Z_BOT - 0.03 : Z_BOT} hovered={hoverNet === t.net} bottom />)}
      </group>
      <group visible={vis('Drill')}>{!flag('novias') && data.vias.map((v, i) => <ViaMesh key={i} via={v} live={data.live} />)}</group>
      {!flag('nosilk') && <group ref={gSilk} visible={vis('F.SilkS')}>
        <SilkLayer board={board} live={data.live} positions={data.positions} />
        {board.texts.map((t, i) => <Label key={i} position={[t.x, t.y, T + 0.06]} rotation={[0, 0, (t.rot * Math.PI) / 180]} size={t.size * 1.3} color="#e8eef5" text={t.text} />)}
      </group>}
      {!flag('noparts') && <group ref={gParts}><Parts board={board} components={data.components} live={data.live} positions={data.positions} /></group>}
      {data.live && !flag('norats') && <Ratsnest lines={data.ratsnest} routed={data.routedNets} failed={data.failedNets} />}
      {data.live && data.drc && !flag('nodrc') && <DrcMarkers drc={data.drc} selected={selected} />}
      {data.live && !flag('nothermal') && <ThermalPlane board={board} thermal={data.thermal} visible={tab === 'thermal'} />}
      {!flag('nolabels') && <group ref={gLabels} visible={false}><LayerLabels board={board} /></group>}
    </group>
  )
}

/* ------------------------------------------------------------------ */
function CameraRig({ center, size, decor }: { center: [number, number]; size: number; decor: boolean }) {
  const controls = useRef<React.ComponentRef<typeof OrbitControls>>(null)
  const { camera } = useThree()
  const idle = useRef(true)
  const idleTimer = useRef(0)
  const fitted = useRef('')
  const exploded = useStore(s => s.exploded)
  const explodeAt = useRef(0)
  useEffect(() => { explodeAt.current = performance.now() }, [exploded])
  useEffect(() => {
    const key = `${center[0]},${center[1]},${size}`
    if (fitted.current === key) return
    fitted.current = key
    const d = size * (decor ? 1.7 : 2.0)
    camera.position.set(center[0] - d * 0.45, center[1] - d * 0.8, d * (decor ? 0.5 : 0.7))
    if (controls.current) { controls.current.target.set(center[0], center[1], 0.8); controls.current.update() }
  }, [center, size, camera, decor])

  useFrame((_, dt) => {
    const c = controls.current; if (!c) return
    if (live.camTarget && performance.now() - live.camTarget.at < 1800 && !decor) {
      const tg = new THREE.Vector3(live.camTarget.x, live.camTarget.y, 0.8)
      c.target.lerp(tg, Math.min(1, dt * 4))
      const want = tg.clone().add(new THREE.Vector3(-6, -9, 12))
      camera.position.lerp(want, Math.min(1, dt * 3))
      c.autoRotate = false
      c.update()
      return
    }
    // when the layer stack explodes/collapses, glide the camera to a distance that frames it
    if (!decor && performance.now() - explodeAt.current < 2500) {
      const want = size * (exploded ? 3.8 : 2.0)
      const dir = camera.position.clone().sub(c.target)
      const dist = dir.length()
      const nd = dist + (want - dist) * Math.min(1, dt * 3)
      const minZ = exploded ? want * 0.62 : 0
      camera.position.copy(c.target).add(dir.multiplyScalar(nd / dist))
      if (camera.position.z < minZ) camera.position.z += (minZ - camera.position.z) * Math.min(1, dt * 3)
      c.update()
    }
    c.autoRotate = idle.current || decor
  })
  const onStart = () => { idle.current = false; window.clearTimeout(idleTimer.current); idleTimer.current = window.setTimeout(() => { idle.current = true }, 7000) }
  return <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.08} autoRotate autoRotateSpeed={decor ? 0.9 : 0.5} minDistance={8} maxDistance={400} maxPolarAngle={Math.PI * 0.95} onStart={onStart} />
}

/* ------------------------------------------------------------------ */
function Substrate({ board, color }: { board: Board; color: MaskColor }) {
  const geo = useMemo(() => {
    const shape = outlineShape(board.outline, board.width, board.height, board.corner_radius)
    for (const h of board.holes) shape.holes.push(circlePath(h.x, h.y, h.drill / 2))
    const g = new THREE.ExtrudeGeometry(shape, { depth: T, bevelEnabled: false, curveSegments: 12 })
    return g
  }, [board])
  const col = useMemo(() => M.maskColor(color), [color])
  return (
    <mesh geometry={geo} receiveShadow>
      <meshStandardMaterial color={col} roughness={0.45} metalness={0.15} />
    </mesh>
  )
}

function ShadowBlob({ board }: { board: Board }) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas'); c.width = c.height = 256
    const ctx = c.getContext('2d')!
    const g = ctx.createRadialGradient(128, 128, 20, 128, 128, 128)
    g.addColorStop(0, 'rgba(0,0,0,0.75)'); g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 256)
    const t = new THREE.CanvasTexture(c); return t
  }, [])
  return (
    <mesh position={[board.width / 2, board.height / 2, -6]}>
      <planeGeometry args={[board.width * 1.9, board.height * 1.9]} />
      <meshBasicMaterial map={tex} transparent depthWrite={false} />
    </mesh>
  )
}

function EdgeCuts({ board }: { board: Board }) {
  const geo = useMemo(() => {
    const shape = outlineShape(board.outline, board.width, board.height, board.corner_radius)
    const pts = shape.getPoints(24)
    return new THREE.BufferGeometry().setFromPoints(pts.map(p => new THREE.Vector3(p.x, p.y, 0)))
  }, [board])
  return <lineLoop geometry={geo}><lineBasicMaterial color="#ffcf5a" /></lineLoop>
}

function MaskGhost({ board, color }: { board: Board; color: MaskColor }) {
  const geo = useMemo(() => new THREE.ShapeGeometry(outlineShape(board.outline, board.width, board.height, board.corner_radius)), [board])
  const col = useMemo(() => M.maskColor(color).lerp(new THREE.Color('#7a3fb0'), 0.5), [color])
  return <mesh geometry={geo} position={[0, 0, T]}><meshStandardMaterial color={col} transparent opacity={0.35} side={THREE.DoubleSide} /></mesh>
}

function DrillHits({ board, vias, positions }: { board: Board; vias: Via[]; positions: Record<string, [number, number, number]> }) {
  const geo = useMemo(() => {
    const geoms: THREE.BufferGeometry[] = []
    for (const v of vias) geoms.push(new THREE.RingGeometry(v.drill / 2, v.drill / 2 + 0.12, 12).translate(v.x, v.y, 0))
    for (const h of board.holes) geoms.push(new THREE.RingGeometry(h.drill / 2, h.drill / 2 + 0.2, 24).translate(h.x, h.y, 0))
    for (const [ref, fp] of Object.entries(board.footprints)) {
      const p = positions[ref]; if (!p) continue
      for (const pad of fp.pads) if (pad.layer === 'through' && pad.drill) {
        const [x, y] = rotPt(pad.x, pad.y, p[2]); geoms.push(new THREE.RingGeometry(pad.drill / 2, pad.drill / 2 + 0.12, 12).translate(p[0] + x, p[1] + y, 0))
      }
    }
    return geoms.length ? mergeGeoms(geoms) : new THREE.BufferGeometry()
  }, [board, vias, positions])
  return <mesh geometry={geo}><meshBasicMaterial color="#9aa7b8" side={THREE.DoubleSide} /></mesh>
}

function LayerLabels({ board }: { board: Board }) {
  const x = -6, y = board.height / 2
  const items: [string, number, string][] = [['PARTS', EX.parts + 2, '#ffffff'], ['F.SilkS', EX.silk, '#e8eef5'], ['F.Mask', EX.mask, '#b48cff'], ['F.Cu', EX.fcu + T, '#e8a35c'], ['FR-4 · 1.6 mm', T / 2, '#7d8a9b'], ['B.Cu · GND pour', EX.bcu, '#4fa3e0'], ['Drill', EX.drill, '#9aa7b8'], ['Edge.Cuts', EX.edge, '#ffcf5a']]
  return <>{items.map(([t, z, c]) => <Label key={t} position={[x, y, z]} size={1.6} color={c} anchorX="right" rotation={[Math.PI / 2, 0, 0]} text={t} />)}</>
}

/* ------------------------------------------------------------------ */
function rotPt(x: number, y: number, deg: number): [number, number] {
  const r = (deg * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r)
  return [x * c - y * s, x * s + y * c]
}

function usePartTransform(ref: string, live_: boolean, positions: Record<string, [number, number, number]>, group: React.RefObject<THREE.Group | null>, zBase: number, landing = false) {
  useFrame((_, dt) => {
    const g = group.current; if (!g) return
    if (!live_) { const p = positions[ref]; if (p) { g.position.set(p[0], p[1], zBase); g.rotation.z = (p[2] * Math.PI) / 180 } return }
    const cur = live.current.get(ref), tg = live.targets.get(ref)
    if (!cur || !tg) return
    const k = Math.min(1, dt * (live.finalSnap ? 10 : 7))
    cur.x += (tg.x - cur.x) * k; cur.y += (tg.y - cur.y) * k
    let dr = ((tg.rot - cur.rot + 540) % 360) - 180; cur.rot += dr * k
    cur.z += (tg.z - cur.z) * Math.min(1, dt * 5)
    let bounce = 0
    if (landing && live.finalSnap) {
      if (!live.landed.has(ref) && cur.z < 0.08) { live.landed.add(ref); (cur as unknown as { landAt: number }).landAt = performance.now() }
      const la = (cur as unknown as { landAt?: number }).landAt
      if (la) { const t = (performance.now() - la) / 1000; if (t < 0.6) bounce = Math.abs(Math.sin(t * 18)) * 0.5 * Math.exp(-t * 7) }
    }
    g.position.set(cur.x, cur.y, zBase + (landing ? cur.z + bounce : cur.z * 0.0))
    g.rotation.z = (cur.rot * Math.PI) / 180
    dr = 0
  })
}

function PadsLayer({ board, live: lv, positions }: { board: Board; live: boolean; positions: Record<string, [number, number, number]> }) {
  return <>{Object.entries(board.footprints).map(([ref, fp]) => <FootprintPads key={ref} refName={ref} fp={fp} live={lv} positions={positions} />)}</>
}

function FootprintPads({ refName, fp, live: lv, positions }: { refName: string; fp: Footprint; live: boolean; positions: Record<string, [number, number, number]> }) {
  const g = useRef<THREE.Group>(null)
  usePartTransform(refName, lv, positions, g, T)
  const { smd, tht } = useMemo(() => {
    const smd: THREE.BufferGeometry[] = [], tht: THREE.BufferGeometry[] = []
    for (const p of fp.pads) {
      if (p.layer === 'through') {
        const r = Math.max(p.w, p.h) / 2
        const s = p.shape === 'rect' || p.shape === 'roundrect' ? roundedRectShape(p.w, p.h, p.shape === 'roundrect' ? Math.min(p.w, p.h) * 0.25 : 0, p.x - p.w / 2, p.y - p.h / 2) : (() => { const sh = new THREE.Shape(); sh.absarc(p.x, p.y, p.shape === 'oval' ? Math.min(p.w, p.h) / 2 : r, 0, Math.PI * 2, false); return sh })()
        if (p.shape === 'oval' && p.w !== p.h) { const sh = roundedRectShape(p.w, p.h, Math.min(p.w, p.h) / 2, p.x - p.w / 2, p.y - p.h / 2); sh.holes.push(circlePath(p.x, p.y, (p.drill ?? 0.6) / 2)); tht.push(new THREE.ExtrudeGeometry(sh, { depth: T + CU * 2, bevelEnabled: false, curveSegments: 8 }).translate(0, 0, -T - CU)) }
        else { s.holes.push(circlePath(p.x, p.y, (p.drill ?? 0.6) / 2)); tht.push(new THREE.ExtrudeGeometry(s, { depth: T + CU * 2, bevelEnabled: false, curveSegments: 8 }).translate(0, 0, -T - CU)) }
      } else smd.push(padGeometry(p.shape, p.x, p.y, p.w, p.h, CU, CU / 2))
    }
    return { smd: smd.length ? mergeGeoms(smd) : null, tht: tht.length ? mergeGeoms(tht) : null }
  }, [fp])
  return (
    <group ref={g}>
      {smd && <mesh geometry={smd} material={M.padGold} />}
      {tht && <mesh geometry={tht} material={M.padGold} />}
    </group>
  )
}

function SilkLayer({ board, live: lv, positions }: { board: Board; live: boolean; positions: Record<string, [number, number, number]> }) {
  return <>{Object.entries(board.footprints).map(([ref, fp]) => <FootprintSilk key={ref} refName={ref} fp={fp} live={lv} positions={positions} />)}</>
}
function FootprintSilk({ refName, fp, live: lv, positions }: { refName: string; fp: Footprint; live: boolean; positions: Record<string, [number, number, number]> }) {
  const g = useRef<THREE.Group>(null)
  usePartTransform(refName, lv, positions, g, T + 0.05)
  const geo = useMemo(() => {
    const pts: THREE.Vector3[] = []
    for (const s of fp.silk) { pts.push(new THREE.Vector3(s[0], s[1], 0), new THREE.Vector3(s[2], s[3], 0)) }
    return new THREE.BufferGeometry().setFromPoints(pts)
  }, [fp])
  const ly = fp.courtyard.y + fp.courtyard.h + 0.9
  return (
    <group ref={g}>
      {fp.silk.length > 0 && <lineSegments geometry={geo} material={M.silkMat} />}
      {fp.body.style !== 'hole' && <Label position={[0, ly, 0]} size={Math.max(0.7, Math.min(1.2, fp.courtyard.w * 0.25))} color="#e8eef5" text={refName} />}
    </group>
  )
}

/* ------------------------------------------------------------------ */
function Parts({ board, components, live: lv, positions }: { board: Board; components: Component[]; live: boolean; positions: Record<string, [number, number, number]> }) {
  const byRef = useMemo(() => Object.fromEntries(components.map(c => [c.ref, c])), [components])
  return <>{Object.entries(board.footprints).map(([ref, fp]) => <Part key={ref} refName={ref} fp={fp} comp={byRef[ref]} live={lv} positions={positions} />)}</>
}

function Part({ refName, fp, comp, live: lv, positions }: { refName: string; fp: Footprint; comp?: Component; live: boolean; positions: Record<string, [number, number, number]> }) {
  const g = useRef<THREE.Group>(null)
  usePartTransform(refName, lv, positions, g, T + CU, true)
  const b = fp.body
  const cx = b.x != null ? b.x + b.w / 2 : 0, cy = b.y != null ? b.y + b.h / 2 : 0
  const style = b.style
  const z = Math.max(0.3, b.z || 1)
  const name = (comp?.name ?? '') + ' ' + (comp?.value ?? '') + ' ' + (comp?.category ?? '')
  const isCap = /cap|capacitor|mlcc|^c\d/i.test(name) || /^C\d/.test(refName)
  const ledMat = useMemo(() => style === 'led' ? new THREE.MeshStandardMaterial({ color: M.ledColorFrom(comp?.value ?? '', comp?.name ?? ''), emissive: M.ledColorFrom(comp?.value ?? '', comp?.name ?? ''), emissiveIntensity: 2.2, transparent: true, opacity: 0.9, roughness: 0.2 }) : null, [style, comp])
  if (style === 'hole') return null

  let body: React.ReactNode = null
  if (style === 'module') {
    body = <>
      <mesh position={[cx, cy, 0.35]} material={M.bodyDark}><boxGeometry args={[b.w, b.h, 0.7]} /></mesh>
      <mesh position={[cx, cy, 0.7 + (z - 0.7) / 2]} material={M.shieldCan}><boxGeometry args={[b.w - 1.2, b.h - 1.2, z - 0.7]} /></mesh>
      {comp && <Label position={[cx, cy, z + 0.02]} size={Math.min(1.4, b.w / 9)} maxWidth={b.w * 0.8} color="#2b2f36" text={comp.name} />}
    </>
  } else if (style === 'chip' || style === 'sot' || style === 'tht') {
    body = <>
      <mesh position={[cx, cy, z / 2]} material={M.bodyBlack}><boxGeometry args={[b.w, b.h, z]} /></mesh>
      <mesh position={[cx - b.w / 2 + Math.min(0.35, b.w * 0.15), cy + b.h / 2 - Math.min(0.35, b.h * 0.15), z + 0.005]} material={M.whiteDot}><circleGeometry args={[Math.min(0.15, b.w * 0.06), 8]} /></mesh>
      {comp && b.w > 3.5 && <Label position={[cx, cy, z + 0.01]} size={Math.min(0.8, b.w / 8)} maxWidth={b.w * 0.85} color="#8a9099" text={comp.name} />}
    </>
  } else if (style === 'passive') {
    const capW = b.w * 0.2
    body = <>
      <mesh position={[cx, cy, z / 2]} material={isCap ? M.capBeige : M.resBody}><boxGeometry args={[b.w * 0.62, b.h, z]} /></mesh>
      {!isCap && <mesh position={[cx, cy, z + 0.01]} material={M.resTop}><boxGeometry args={[b.w * 0.5, b.h * 0.8, 0.02]} /></mesh>}
      <mesh position={[cx - b.w / 2 + capW / 2, cy, z / 2]} material={M.endCap}><boxGeometry args={[capW, b.h, z]} /></mesh>
      <mesh position={[cx + b.w / 2 - capW / 2, cy, z / 2]} material={M.endCap}><boxGeometry args={[capW, b.h, z]} /></mesh>
    </>
  } else if (style === 'electrolytic') {
    const r = Math.min(b.w, b.h) / 2
    body = <>
      <mesh position={[cx, cy, z / 2]} material={M.electrolytic}><cylinderGeometry args={[r, r, z, 24]} /></mesh>
      <mesh position={[cx, cy, z]} material={M.endCap}><circleGeometry args={[r * 0.9, 24]} /></mesh>
    </>
  } else if (style === 'usb') {
    const geo = new THREE.ExtrudeGeometry(roundedRectShape(b.w, z, Math.min(z / 2 - 0.05, 1.2), -b.w / 2, 0), { depth: b.h, bevelEnabled: false })
    body = <mesh geometry={geo} position={[cx, cy + b.h / 2, 0]} rotation={[Math.PI / 2, 0, 0]} material={M.connectorMetal} />
  } else if (style === 'connector') {
    body = <mesh position={[cx, cy, z / 2]} material={M.connectorMetal}><boxGeometry args={[b.w, b.h, z]} /></mesh>
  } else if (style === 'header') {
    body = <>
      <mesh position={[cx, cy, 1.25]} material={M.plasticBlack}><boxGeometry args={[b.w, b.h, 2.5]} /></mesh>
      {fp.pads.map((p, i) => <mesh key={i} position={[p.x, p.y, (z + 1) / 2]} material={M.goldPin}><boxGeometry args={[0.64, 0.64, z + 1]} /></mesh>)}
    </>
  } else if (style === 'led') {
    body = <mesh position={[cx, cy, z / 2]} material={ledMat!}><boxGeometry args={[b.w * 0.9, b.h, z]} /></mesh>
  } else if (style === 'switch') {
    const r = Math.min(b.w, b.h) * 0.3
    body = <>
      <mesh position={[cx, cy, z * 0.3]} material={M.plasticBlack}><boxGeometry args={[b.w, b.h, z * 0.6]} /></mesh>
      <mesh position={[cx, cy, z * 0.6 + z * 0.2]} material={M.switchBtn} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[r, r, z * 0.4, 20]} /></mesh>
    </>
  } else if (style === 'crystal') {
    const geo = new THREE.ExtrudeGeometry(roundedRectShape(b.w, b.h, Math.min(b.w, b.h) * 0.3, -b.w / 2, -b.h / 2), { depth: z, bevelEnabled: false })
    body = <mesh geometry={geo} position={[cx, cy, 0]} material={M.crystalCan} />
  } else {
    body = <mesh position={[cx, cy, z / 2]} material={M.bodyBlack}><boxGeometry args={[b.w, b.h, z]} /></mesh>
  }
  return <group ref={g}>{body}</group>
}

/* ------------------------------------------------------------------ */
function TraceMesh({ trace, z, hovered, bottom }: { trace: Trace; z: number; hovered: boolean; bottom?: boolean }) {
  const geo = useMemo(() => polylineGeometry(trace.points, trace.width), [trace])
  const total = useMemo(() => pathLength(trace.points), [trace])
  const mesh = useRef<THREE.Mesh>(null)
  const head = useRef<THREE.Mesh>(null)
  const meta = live.traceMeta.get(trace)
  const finished = useRef(!meta)
  const count = geo.getAttribute('position')?.count ?? 0
  useEffect(() => { if (meta && mesh.current) geo.setDrawRange(0, 0) }, [geo, meta])
  useFrame(() => {
    if (finished.current || !meta) return
    const k = (performance.now() - meta.startAt) / meta.duration
    if (k <= 0) { geo.setDrawRange(0, 0); if (head.current) head.current.visible = false; return }
    if (k >= 1) { geo.setDrawRange(0, Infinity); finished.current = true; if (head.current) head.current.visible = false; return }
    geo.setDrawRange(0, Math.floor(k * count / 3) * 3)
    if (head.current) { const [x, y] = pointAt(trace.points, k); head.current.position.set(x, y, z + (bottom ? -0.3 : 0.3)); head.current.visible = true; head.current.scale.setScalar(1 + Math.sin(k * Math.PI) * 0.6) }
  })
  const mat = hovered ? M.hoverMat : bottom ? M.copperBottom : M.copperTop
  return (
    <>
      <mesh ref={mesh} geometry={geo} material={mat} position={[0, 0, z]} />
      {meta && !finished.current && (
        <mesh ref={head} visible={false} material={M.headMat}><sphereGeometry args={[Math.max(0.35, trace.width * 1.2), 10, 10]} /></mesh>
      )}
      {meta && !finished.current && total > 0 && null}
    </>
  )
}

function ViaMesh({ via, live: lv }: { via: Via; live: boolean }) {
  const g = useRef<THREE.Group>(null)
  const born = useRef(performance.now())
  useFrame(() => {
    if (!g.current || !lv) return
    const t = (performance.now() - born.current) / 220
    const s = t >= 1 ? 1 : 1 - Math.pow(1 - t, 3) * (1 + Math.sin(t * 6) * 0.2)
    g.current.scale.setScalar(Math.max(0.001, s))
  })
  const r = via.diameter / 2, rd = via.drill / 2
  return (
    <group ref={g} position={[via.x, via.y, T / 2]}>
      <mesh material={M.viaMat}><cylinderGeometry args={[rd + 0.02, rd + 0.02, T + CU * 2, 12, 1, true]} /></mesh>
      <mesh position={[0, 0, T / 2 + CU / 2]} material={M.viaMat} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[r, r, CU, 16]} /></mesh>
      <mesh position={[0, 0, -T / 2 - CU / 2]} material={M.viaMat} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[r, r, CU, 16]} /></mesh>
      <mesh position={[0, 0, T / 2 + CU]} material={M.bodyBlack}><circleGeometry args={[rd, 12]} /></mesh>
      <mesh position={[0, 0, -T / 2 - CU]} material={M.bodyBlack} rotation={[Math.PI, 0, 0]}><circleGeometry args={[rd, 12]} /></mesh>
    </group>
  )
}

function Pour({ board, color, traces, vias, clearance, gndNet, positions }: { board: Board; color: MaskColor; traces: Trace[]; vias: Via[]; clearance: number; gndNet: string; positions: Record<string, [number, number, number]> }) {
  const planeGeo = useMemo(() => {
    const shape = outlineShape(board.outline, board.width, board.height, board.corner_radius)
    for (const h of board.holes) shape.holes.push(circlePath(h.x, h.y, h.diameter / 2))
    return new THREE.ShapeGeometry(shape, 12)
  }, [board])
  const gapGeo = useMemo(() => {
    const geoms: THREE.BufferGeometry[] = []
    for (const t of traces) if (t.net !== gndNet) geoms.push(polylineGeometry(t.points, t.width + clearance * 2, 8))
    for (const v of vias) if (v.net !== gndNet) geoms.push(new THREE.CircleGeometry(v.diameter / 2 + clearance, 16).translate(v.x, v.y, 0))
    for (const [ref, fp] of Object.entries(board.footprints)) {
      const p = positions[ref]; if (!p) continue
      for (const pad of fp.pads) if (pad.layer === 'through') { const [x, y] = rotPt(pad.x, pad.y, p[2]); geoms.push(new THREE.CircleGeometry(Math.max(pad.w, pad.h) / 2 + clearance, 16).translate(p[0] + x, p[1] + y, 0)) }
    }
    return geoms.length ? mergeGeoms(geoms) : null
  }, [traces, vias, clearance, gndNet, board, positions])
  const tint = useMemo(() => M.pourTint(color), [color])
  const mask = useMemo(() => M.maskColor(color), [color])
  return (
    <group>
      <mesh geometry={planeGeo} position={[0, 0, -0.02]} rotation={[0, 0, 0]}><meshStandardMaterial color={tint} metalness={0.6} roughness={0.5} side={THREE.DoubleSide} /></mesh>
      {gapGeo && <mesh geometry={gapGeo} position={[0, 0, -0.045]}><meshStandardMaterial color={mask} roughness={0.5} side={THREE.DoubleSide} /></mesh>}
    </group>
  )
}

/* ------------------------------------------------------------------ */
function Ratsnest({ lines, routed, failed }: { lines: [number, number, number, number, string][]; routed: string[]; failed: string[] }) {
  const { geo, bad } = useMemo(() => {
    const set = new Set(routed), fset = new Set(failed)
    const pts: THREE.Vector3[] = [], badPts: THREE.Vector3[] = []
    for (const l of lines) {
      if (fset.has(l[4])) { badPts.push(new THREE.Vector3(l[0], l[1], T + 0.5), new THREE.Vector3(l[2], l[3], T + 0.5)); continue }
      if (!set.has(l[4])) pts.push(new THREE.Vector3(l[0], l[1], T + 0.4), new THREE.Vector3(l[2], l[3], T + 0.4))
    }
    return { geo: new THREE.BufferGeometry().setFromPoints(pts), bad: new THREE.BufferGeometry().setFromPoints(badPts) }
  }, [lines, routed, failed])
  return <>
    <lineSegments geometry={geo} material={M.ratsnestMat} />
    <lineSegments geometry={bad} material={M.failMat} />
  </>
}

function DrcMarkers({ drc, selected }: { drc: Drc; selected: unknown }) {
  const g = useRef<THREE.Group>(null)
  useFrame(({ clock }) => {
    if (!g.current) return
    const t = clock.elapsedTime
    g.current.children.forEach((c, i) => { const s = 1 + 0.35 * Math.sin(t * 4 + i); c.scale.set(s, s, 1) })
  })
  const flash = drc.passed && drc.violations.length === 0
  return (
    <>
      <group ref={g}>
        {drc.violations.map((v, i) => {
          const z = v.layer === 'B.Cu' ? -0.4 : T + 0.4
          const sel = v === selected
          return (
            <group key={i} position={[v.x, v.y, z]}>
              <mesh material={M.drcMat}><ringGeometry args={[sel ? 1.2 : 0.7, sel ? 1.6 : 1.0, 32]} /></mesh>
              {sel && <mesh position={[0, 0, 8]} material={M.drcMat}><cylinderGeometry args={[0.08, 0.08, 16, 6]} /></mesh>}
            </group>
          )
        })}
      </group>
      {flash && <PassFlash />}
    </>
  )
}
function PassFlash() {
  const m = useRef<THREE.MeshBasicMaterial>(null)
  const born = useRef(performance.now())
  const board = useStore(s => s.board)!
  useFrame(() => { if (m.current) { const t = (performance.now() - born.current) / 1800; m.current.opacity = Math.max(0, 0.9 * (1 - t)) * (0.6 + 0.4 * Math.sin(t * 20)) } })
  const geo = useMemo(() => { const s = outlineShape(board.outline, board.width, board.height, board.corner_radius); return new THREE.BufferGeometry().setFromPoints(s.getPoints(24).map(p => new THREE.Vector3(p.x, p.y, T + 0.2))) }, [board])
  return <lineLoop geometry={geo}><lineBasicMaterial ref={m} color="#7cff5a" transparent opacity={0.9} toneMapped={false} /></lineLoop>
}

function ThermalPlane({ board, thermal, visible }: { board: Board; thermal: ThermalFrame | null; visible: boolean }) {
  const tex = useMemo(() => {
    if (!thermal) return null
    const data = new Uint8Array(thermal.cols * thermal.rows * 4)
    const lo = thermal.min_c, hi = Math.max(thermal.max_c, lo + 5)
    for (let i = 0; i < thermal.cols * thermal.rows; i++) {
      const [r, g, b] = turbo((thermal.grid[i] - lo) / (hi - lo))
      data[i * 4] = r; data[i * 4 + 1] = g; data[i * 4 + 2] = b; data[i * 4 + 3] = 255
    }
    const t = new THREE.DataTexture(data, thermal.cols, thermal.rows, THREE.RGBAFormat)
    t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearFilter; t.needsUpdate = true
    return t
  }, [thermal])
  useEffect(() => () => { tex?.dispose() }, [tex])
  if (!tex || !visible) return null
  return (
    <mesh position={[board.width / 2, board.height / 2, T + 0.08]}>
      <planeGeometry args={[board.width, board.height]} />
      <meshBasicMaterial map={tex} transparent opacity={0.92} toneMapped={false} />
    </mesh>
  )
}

/* ------------------------------------------------------------------ */
/** Decorative procedural board for the landing page. */
function DecorBoard() {
  const [data] = useState<SceneData>(() => makeDecor())
  return <BoardContent data={data} />
}

function makeDecor(): SceneData {
  const W = 84, H = 56
  let seed = 7
  const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646 }
  const footprints: Record<string, Footprint> = {}
  const positions: Record<string, [number, number, number]> = {}
  const components: Component[] = []
  const mk = (ref: string, style: string, w: number, h: number, z: number, x: number, y: number, rot: number, pads: [number, number, number, number][], cat = 'ic', name = '') => {
    footprints[ref] = { pads: pads.map((p, i) => ({ num: String(i + 1), shape: 'roundrect', x: p[0], y: p[1], w: p[2], h: p[3], layer: 'F.Cu' })), courtyard: { x: -w / 2 - 0.5, y: -h / 2 - 0.5, w: w + 1, h: h + 1 }, body: { x: -w / 2, y: -h / 2, w, h, z, style }, silk: [] }
    positions[ref] = [x, y, rot]
    components.push({ ref, part_id: ref, name, value: '', category: cat, description: '', footprint: '', package: '', pins: [], body: { w, h, z, style } })
  }
  const modPads: [number, number, number, number][] = []
  for (let i = 0; i < 12; i++) { modPads.push([-9.5, 7 - i * 1.27, 1.2, 0.8]); modPads.push([9.5, 7 - i * 1.27, 1.2, 0.8]) }
  mk('U1', 'module', 18, 25.5, 3.1, 22, 30, 0, modPads, 'mcu', 'ESP32-WROOM-32E')
  const qfp: [number, number, number, number][] = []
  for (let i = 0; i < 12; i++) { qfp.push([-4.6, 2.75 - i * 0.5, 1.2, 0.3]); qfp.push([4.6, 2.75 - i * 0.5, 1.2, 0.3]); qfp.push([2.75 - i * 0.5, -4.6, 0.3, 1.2]); qfp.push([2.75 - i * 0.5, 4.6, 0.3, 1.2]) }
  mk('U2', 'chip', 7, 7, 1.4, 52, 36, 0, qfp, 'ic', 'STM32')
  const soic: [number, number, number, number][] = []
  for (let i = 0; i < 4; i++) { soic.push([-2.7, 1.9 - i * 1.27, 1.5, 0.6]); soic.push([2.7, 1.9 - i * 1.27, 1.5, 0.6]) }
  mk('U3', 'chip', 4, 5, 1.5, 66, 20, 90, soic, 'ic', 'W25Q')
  mk('U4', 'sot', 3, 1.6, 1.1, 50, 14, 0, [[-0.95, -1.1, 0.6, 1.1], [0, -1.1, 0.6, 1.1], [0.95, -1.1, 0.6, 1.1], [0.95, 1.1, 0.6, 1.1], [-0.95, 1.1, 0.6, 1.1]], 'power', 'LDO')
  mk('J1', 'usb', 9, 7.4, 3.2, 78, 40, 90, [[-3, 2.5, 0.6, 1.2], [-1, 2.5, 0.6, 1.2], [1, 2.5, 0.6, 1.2], [3, 2.5, 0.6, 1.2]], 'connector')
  mk('J2', 'header', 2.54, 20.32, 8.5, 5, 28, 0, Array.from({ length: 8 }, (_, i) => [0, 8.89 - i * 2.54, 1.7, 1.7] as [number, number, number, number]), 'connector')
  mk('Y1', 'crystal', 3.2, 2.5, 0.8, 60, 28, 0, [[-1.1, 0.8, 1.2, 1.0], [1.1, 0.8, 1.2, 1.0], [-1.1, -0.8, 1.2, 1.0], [1.1, -0.8, 1.2, 1.0]], 'crystal')
  mk('SW1', 'switch', 6, 6, 3.5, 40, 8, 0, [[-3.2, 2.2, 1.6, 1.2], [3.2, 2.2, 1.6, 1.2], [-3.2, -2.2, 1.6, 1.2], [3.2, -2.2, 1.6, 1.2]], 'switch')
  mk('C9', 'electrolytic', 6.3, 6.3, 5.8, 70, 8, 0, [[-2.5, 0, 1.6, 2.4], [2.5, 0, 1.6, 2.4]], 'passive', 'Capacitor')
  const pas: [number, number, number, number][] = [[-0.9, 0, 0.9, 0.9], [0.9, 0, 0.9, 0.9]]
  const spots: [number, number, number][] = [[36, 42, 90], [36, 38, 90], [36, 34, 90], [44, 24, 0], [48, 24, 0], [56, 46, 0], [60, 46, 0], [64, 46, 0], [58, 10, 90], [62, 10, 90], [14, 12, 0], [18, 12, 0], [22, 12, 0], [26, 12, 0], [44, 30, 90], [47, 30, 90]]
  spots.forEach((s, i) => mk(i % 3 === 2 ? `R${i}` : `C${i}`, 'passive', 1.6, 0.8, 0.5, s[0], s[1], s[2], pas, 'passive', i % 3 === 2 ? 'Resistor' : 'Capacitor'))
  mk('D1', 'led', 1.6, 0.8, 0.6, 10, 46, 0, pas, 'led', 'LED cyan')
  mk('D2', 'led', 1.6, 0.8, 0.6, 10, 42, 0, pas, 'led', 'LED red')
  mk('D3', 'led', 1.6, 0.8, 0.6, 10, 38, 0, pas, 'led', 'LED green')
  // traces: random manhattan walks between parts
  const traces: Trace[] = []
  const vias: Via[] = []
  const refs = Object.keys(positions)
  for (let i = 0; i < 70; i++) {
    const a = positions[refs[Math.floor(rnd() * refs.length)]], b = positions[refs[Math.floor(rnd() * refs.length)]]
    if (a === b) continue
    const ax = a[0] + (rnd() - 0.5) * 6, ay = a[1] + (rnd() - 0.5) * 6, bx = b[0] + (rnd() - 0.5) * 6, by = b[1] + (rnd() - 0.5) * 6
    const midx = ax + (bx - ax) * (0.3 + rnd() * 0.4)
    const d = Math.min(Math.abs(by - ay), Math.abs(bx - midx)) * 0.5
    const pts = [[ax, ay], [midx - Math.sign(midx - ax) * 0, ay], [midx, ay + Math.sign(by - ay) * Math.min(Math.abs(by - ay), 0.001 + d)], [midx, by], [bx, by]].map(p => [Math.max(2, Math.min(W - 2, p[0])), Math.max(2, Math.min(H - 2, p[1]))])
    const bottom = rnd() < 0.3
    const width = rnd() < 0.2 ? 0.5 : 0.25
    if (bottom) {
      traces.push({ net: `N${i}`, layer: 'F.Cu', width, points: pts.slice(0, 2) })
      vias.push({ net: `N${i}`, x: pts[1][0], y: pts[1][1], drill: 0.3, diameter: 0.6 })
      traces.push({ net: `N${i}`, layer: 'B.Cu', width, points: pts.slice(1, 4) })
      vias.push({ net: `N${i}`, x: pts[3][0], y: pts[3][1], drill: 0.3, diameter: 0.6 })
      traces.push({ net: `N${i}`, layer: 'F.Cu', width, points: pts.slice(3) })
    } else traces.push({ net: `N${i}`, layer: 'F.Cu', width, points: pts })
  }
  const board: Board = { width: W, height: H, corner_radius: 3, color: 'black', outline: [[0, 0], [W, 0], [W, H], [0, H]], holes: [[3.5, 3.5], [W - 3.5, 3.5], [3.5, H - 3.5], [W - 3.5, H - 3.5]].map(([x, y]) => ({ x, y, drill: 3.2, diameter: 6 })), footprints, texts: [{ text: 'ETCH · REFERENCE', x: W / 2, y: H - 2.2, size: 1.2, layer: 'F.SilkS', rot: 0 }] }
  return { board, components, traces, vias, pour: { clearance: 0.3, net: 'GND' }, color: 'black', ratsnest: [], routedNets: [], failedNets: [], drc: null, thermal: null, positions, nets: [], live: false }
}
