import { WS_BASE, api } from './config'
import { useStore } from './store'
import type { Event, MaskColor } from './protocol'
import { generateMockRun } from './mock/mockRun'
import { live } from './live'

let socket: WebSocket | null = null
let replayTimer: number | null = null
let replayCancel = false

function stopAll() {
  if (socket) { try { socket.close() } catch { /* noop */ } socket = null }
  if (replayTimer) { clearTimeout(replayTimer); replayTimer = null }
  replayCancel = true
}

export function startLive(prompt: string, color: MaskColor, demo = false) {
  stopAll()
  const st = useStore.getState()
  st.setMode('live')
  st.reset()
  st.setPrompt(prompt)
  st.setColor(color)
  st.setConnection('connecting')
  live.runStart = performance.now()
  const ws = new WebSocket(`${WS_BASE}/ws/design`)
  socket = ws
  ws.onopen = () => {
    useStore.getState().setConnection('open')
    ws.send(JSON.stringify({ type: 'start', prompt, options: { color, demo } }))
  }
  ws.onmessage = (m) => {
    try {
      const ev = JSON.parse(m.data) as Event
      useStore.getState().applyEvent(ev)
    } catch (e) { console.warn('bad event', e) }
  }
  ws.onerror = () => {
    const s = useStore.getState()
    s.setConnection('error')
    s.setToast('Connection to the ETCH engine failed. Is the backend running on :8000?')
    if (s.phase === 'running') s.setPhase('error')
  }
  ws.onclose = () => {
    const s = useStore.getState()
    if (s.connection !== 'error') s.setConnection('closed')
    if (s.phase === 'running') {
      s.setToast('Engine disconnected before the run finished.')
      s.setPhase('error')
    }
  }
}

export function cancelLive() {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'cancel' }))
  stopAll()
}

/** Play a list of timestamped events honoring their `t` gaps (scaled by store.replaySpeed).
 *  Uses a virtual clock with catch-up so a starved main thread never stalls the run. */
export function playEvents(events: Event[], mode: 'replay' | 'mock') {
  stopAll()
  replayCancel = false
  const st = useStore.getState()
  st.setMode(mode)
  st.reset()
  st.setConnection('open')
  live.runStart = performance.now()
  let i = 0
  const t0 = events[0]?.t ?? 0
  let vt = 0 // virtual seconds elapsed
  let lastNow = performance.now()
  const step = () => {
    if (replayCancel) return
    const now = performance.now()
    const speed = useStore.getState().replaySpeed || 1
    vt += ((now - lastNow) / 1000) * speed
    lastNow = now
    let n = 0
    while (i < events.length && ((events[i].t ?? t0) - t0) <= vt && n < 200) {
      useStore.getState().applyEvent(events[i]); i++; n++
    }
    if (i >= events.length) return
    const wait = Math.max(16, (((events[i].t ?? t0) - t0 - vt) * 1000) / speed)
    replayTimer = window.setTimeout(step, Math.min(wait, 1000))
  }
  step()
}

export async function startReplay(runId: string) {
  const s = useStore.getState()
  try {
    let r = await fetch(api(`/api/runs/${runId}/events.json`)).catch(() => null)
    if (!r || !r.ok) r = await fetch(`/demo/${runId}/events.json`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const events = (await r.json()) as Event[]
    playEvents(events, 'replay')
  } catch (e) {
    s.setToast(`Could not load run ${runId}: ${(e as Error).message}`)
  }
}

export function startMock(color: MaskColor = 'black') {
  const events = generateMockRun(color)
  useStore.getState().setPrompt('Mock run — synthetic 40×30 mm sensor board')
  playEvents(events, 'mock')
}
