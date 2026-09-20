import { useEffect, useState } from 'react'
import { useStore } from '../store'
import { AgentPanel } from './AgentPanel'
import { StatsPanel } from './StatsPanel'
import { Viewport } from './Viewport'
import { fmtTime } from '../util/format'
import { cancelLive, startReplay, playEvents } from '../ws'

export function Workspace() {
  const prompt = useStore(s => s.prompt)
  const phase = useStore(s => s.phase)
  const stage = useStore(s => s.stage)
  const routing = useStore(s => s.routing)
  const mode = useStore(s => s.mode)
  const runId = useStore(s => s.runId)
  const setPhase = useStore(s => s.setPhase)
  const replaySpeed = useStore(s => s.replaySpeed); const setReplaySpeed = useStore(s => s.setReplaySpeed)
  const [clock, setClock] = useState(0)
  const elapsed = useStore(s => s.elapsed)

  useEffect(() => {
    if (phase !== 'running') return
    const t0 = performance.now() - elapsed * 1000
    const id = setInterval(() => setClock((performance.now() - t0) / 1000), 100)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase])

  const back = () => { cancelLive(); setPhase('landing') }
  const replay = () => {
    if (mode === 'mock') playEvents(useStore.getState().events, 'mock')
    else if (runId) startReplay(runId)
    else playEvents(useStore.getState().events, 'replay')
  }

  return (
    <div className="workspace">
      <div className="topbar">
        <div className="brand-mini" onClick={back} style={{ position: 'static' }}>ETCH</div>
        <div className="prompt"><b>▸</b> {prompt}</div>
        <div className="ticker">
          {mode !== 'live' && (
            <span className="replay-ctl"><span className="lbl">{mode.toUpperCase()}</span>
              {[0.5, 1, 2, 5].map(s => <button key={s} className={`mini-btn ${replaySpeed === s ? 'on' : ''}`} onClick={() => setReplaySpeed(s)}>{s}×</button>)}
            </span>
          )}
          {phase === 'running' && <span className="live">LIVE · {stage?.toUpperCase() ?? '…'}</span>}
          {phase === 'done' && <span style={{ color: 'var(--green)' }}>■ COMPLETE</span>}
          {phase === 'error' && <span style={{ color: 'var(--magenta)' }}>■ HALTED</span>}
          <span>NETS <b>{routing.routed}/{routing.total}</b></span>
          <span>T+ <b>{fmtTime(phase === 'running' ? clock : elapsed)}</b></span>
          {phase !== 'running' && <button className="mini-btn" onClick={replay}>↻ REPLAY</button>}
          <button className="mini-btn" onClick={back}>✕ NEW</button>
        </div>
      </div>
      <div className="col"><AgentPanel /></div>
      <div className="col"><Viewport /></div>
      <div className="col"><StatsPanel /></div>
    </div>
  )
}
