// Mutable, non-reactive state shared with the R3F scene. Never triggers React renders.
import type { Trace } from './protocol'

export interface LivePos { x: number; y: number; rot: number; z: number }

export interface LiveTrace {
  trace: Trace
  startAt: number // performance.now() ms
  duration: number
}

export const live = {
  targets: new Map<string, LivePos>(),   // where components should be
  current: new Map<string, LivePos>(),   // where they are (lerped by the scene)
  landed: new Set<string>(),             // placement_final reached -> bounce once
  finalSnap: false,
  traceQueue: [] as LiveTrace[],
  traceMeta: new WeakMap<Trace, LiveTrace>(),
  lastTraceStart: 0,
  runStart: 0,
  camTarget: null as null | { x: number; y: number; at: number },
  boardW: 60,
  boardH: 40,
}

export function scatterInitial(refs: string[], w: number, h: number) {
  live.targets.clear(); live.current.clear(); live.landed.clear(); live.finalSnap = false
  live.boardW = w; live.boardH = h
  refs.forEach((r, i) => {
    const a = (i / Math.max(1, refs.length)) * Math.PI * 2 + 0.7
    const rad = Math.max(w, h) * (0.45 + 0.3 * ((i * 7919) % 100) / 100)
    const p: LivePos = { x: w / 2 + Math.cos(a) * rad, y: h / 2 + Math.sin(a) * rad, rot: ((i * 37) % 4) * 90, z: 22 + ((i * 31) % 12) }
    live.current.set(r, { ...p })
    live.targets.set(r, { ...p })
  })
}

export function setTargets(pos: Record<string, [number, number, number]>, z = 0) {
  for (const [ref, [x, y, rot]] of Object.entries(pos)) {
    const t = live.targets.get(ref)
    if (t) { t.x = x; t.y = y; t.rot = rot; t.z = z }
    else live.targets.set(ref, { x, y, rot, z })
    if (!live.current.has(ref)) live.current.set(ref, { x, y, rot, z: 25 })
  }
}

export function enqueueTrace(trace: Trace) {
  const now = performance.now()
  const backlog = live.traceQueue.filter(t => t.startAt + t.duration > now).length
  // adaptive pacing: fast when a burst arrives
  const stagger = backlog > 40 ? 12 : backlog > 15 ? 40 : 90
  const duration = backlog > 40 ? 120 : backlog > 15 ? 180 : 260
  const startAt = Math.max(now, live.lastTraceStart + stagger)
  live.lastTraceStart = startAt
  const lt = { trace, startAt, duration }
  live.traceQueue.push(lt)
  live.traceMeta.set(trace, lt)
  if (live.traceQueue.length > 400) live.traceQueue.splice(0, live.traceQueue.length - 400)
}
