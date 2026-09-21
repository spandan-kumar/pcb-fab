import { usePop } from '../util/usePop'
import { Suspense, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useStore, type Tab } from '../store'
import { BoardScene } from '../three/BoardScene'
import { Schematic } from '../schematic/Schematic'
import { fmt, fmtInt, fmtTime } from '../util/format'

const TABS: { id: Tab; label: string }[] = [
  { id: 'board', label: 'BOARD 3D' }, { id: 'schematic', label: 'SCHEMATIC' }, { id: 'layers', label: 'LAYERS' }, { id: 'thermal', label: 'THERMAL' },
]
const LAYERS = [
  { id: 'F.Cu', c: '#e8a35c' }, { id: 'F.Mask', c: '#7a3fb0' }, { id: 'F.SilkS', c: '#e8eef5' }, { id: 'Edge.Cuts', c: '#ffcf5a' }, { id: 'B.Cu', c: '#4fa3e0' }, { id: 'Drill', c: '#9aa7b8' },
]

export function Viewport() {
  const tab = useStore(s => s.tab); const setTab = useStore(s => s.setTab)
  const routing = useStore(s => s.routing)
  const drc = useStore(s => s.drc)
  const elapsed = useStore(s => s.elapsed)
  const phase = useStore(s => s.phase)
  const stage = useStore(s => s.stage)
  const thermal = useStore(s => s.thermal)
  const layerVis = useStore(s => s.layerVis); const toggleLayer = useStore(s => s.toggleLayer)
  const placement = useStore(s => s.placementInfo)
  const pour = useStore(s => s.pour)
  const stats = useStore(s => s.stats)
  const flash = useStore(s => s.flash)
  const view = useStore(s => s.view); const setView = useStore(s => s.setView)
  const popNets = usePop(routing.routed)
  const popVias = usePop(routing.vias)
  const failedNets = useStore(s => s.failedNets)
  const [, tick] = useState(0)
  useEffect(() => { if (!flash) return; const id = setTimeout(() => tick(n => n + 1), 2600); return () => clearTimeout(id) }, [flash])
  const flashVisible = flash && performance.now() - flash.at < 2500
  const errs = drc ? (drc.errors ?? drc.violations.filter(v => v.severity === 'error').length) : null

  return (
    <div className="panel bracket viewport" style={{ flex: 1 }}>
      <div className="tabs">
        {TABS.map(t => <button key={t.id} className={`tab ${tab === t.id ? 'on' : ''}`} onClick={() => setTab(t.id)}>{t.label}</button>)}
        <div className="right">
          {tab === 'board' && <button className={`badge toggle ${view === 'top' ? 'on' : ''}`} onClick={() => setView(view === 'top' ? 'iso' : 'top')} title="Toggle top-down view">{view === 'top' ? '⬒ TOP' : '◈ 3D'}</button>}
          {stage === 'placement' && placement && <span className="badge cyan">anneal T={fmt(placement.temperature, 1)} · cost {fmtInt(placement.cost)}</span>}
          {stage === 'routing' && <span className="badge copper">routing · {routing.routed}/{routing.total}</span>}
          {pour && <span className="badge cyan">B.Cu GND pour{pour.islands_healed ? ` · ${pour.islands_healed} islands healed` : ''}{pour.orphans ? ` · ${pour.orphans} orphans` : ''}</span>}
          {failedNets.length > 0 && <span className="badge mag">{failedNets.length} unrouted</span>}
          <AnimatePresence>{flashVisible && <motion.span key={flash!.at} className="badge mag flash" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}>⟲ {flash!.text}</motion.span>}</AnimatePresence>
          {drc && (errs === 0 ? <span className="badge green">DRC PASS</span> : <span className="badge mag">DRC {errs} ERR</span>)}
        </div>
      </div>
      <div className="canvas-wrap">
        <Suspense fallback={null}><BoardScene /></Suspense>
        <AnimatePresence>
          {tab === 'schematic' && (
            <motion.div key="schem" className="schem" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}>
              <Schematic />
            </motion.div>
          )}
        </AnimatePresence>
        {tab === 'layers' && (
          <div className="layer-list">
            {LAYERS.map(l => <button key={l.id} className={layerVis[l.id] ? 'on' : ''} onClick={() => toggleLayer(l.id)}><span className="sw" style={{ background: l.c, opacity: layerVis[l.id] ? 1 : 0.25 }} />{l.id}</button>)}
          </div>
        )}
        {tab === 'thermal' && thermal && (
          <div className="colorbar panel">
            <div className="lbl"><span>{fmt(thermal.min_c, 1)} °C</span><span>steady-state · frame {thermal.frame}/{thermal.total}</span><span>{fmt(thermal.max_c, 1)} °C</span></div>
            <div className="bar" />
            <div className="hotspots">{thermal.hotspots.map(h => <span key={h.ref} className="hot">{h.ref} {fmt(h.c, 1)}°</span>)}</div>
          </div>
        )}
        {tab !== 'schematic' && (
          <div className="hud">
            <div className={`cell ${popNets}`}><div className="k">nets</div><div className="v cyan">{routing.routed}<small>/ {routing.total}</small></div></div>
            <div className={`cell ${popVias}`}><div className="k">trace</div><div className="v copper">{fmt(stats?.total_trace_mm ?? routing.length_mm, 0)}<small>mm</small></div></div>
            <div className={`cell ${popVias}`}><div className="k">vias</div><div className="v copper">{stats?.vias ?? routing.vias}</div></div>
            <div className="cell"><div className="k">drc</div><div className={`v ${errs == null ? '' : errs ? 'mag' : 'green'}`}>{errs == null ? '—' : errs}</div></div>
            <div className="cell"><div className="k">elapsed</div><div className="v">{fmtTime(stats?.elapsed_s ?? elapsed)}</div></div>
          </div>
        )}
        <AnimatePresence>
          {phase === 'done' && stats && (
            <motion.div className="done-banner" initial={{ y: 20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ opacity: 0 }}>
              ■ BOARD COMPLETE · {stats.components} PARTS · {stats.nets} NETS · {fmt(stats.total_trace_mm, 0)} mm · {stats.drc_errors} DRC ERRORS
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
