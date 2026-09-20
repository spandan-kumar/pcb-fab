import { motion, AnimatePresence } from 'framer-motion'
import { useStore } from '../store'
import { fmt, fmtBytes, fmtInt } from '../util/format'
import { useCountUp } from '../util/useCountUp'
import type { Spice } from '../protocol'

function Tile({ k, v, unit, tone, d = 0 }: { k: string; v: number; unit?: string; tone?: string; d?: number }) {
  const n = useCountUp(v, 450)
  return (
    <div className={`tile ${tone ?? ''}`}>
      <div className="k">{k}</div>
      <div className="v">{d ? fmt(n, d) : fmtInt(n)}{unit && <small>{unit}</small>}</div>
    </div>
  )
}

function SpiceChart({ s }: { s: Spice }) {
  const W = 276, H = 120, p = 6
  const left = s.series.filter(q => q.axis !== 'right'), right = s.series.filter(q => q.axis === 'right')
  const xs = s.series.flatMap(q => q.x)
  const x0 = Math.min(...xs), x1 = Math.max(...xs)
  const range = (qs: typeof s.series) => { const ys = qs.flatMap(q => q.y); return ys.length ? [Math.min(...ys), Math.max(...ys)] : [0, 1] }
  const [ly0, ly1] = range(left), [ry0, ry1] = range(right)
  const sx = (x: number) => p + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * p)
  const sy = (y: number, lo: number, hi: number) => H - p - ((y - lo) / (hi - lo || 1)) * (H - 2 * p)
  const path = (q: Spice['series'][number], lo: number, hi: number) => q.x.map((x, j) => `${j ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(q.y[j], lo, hi).toFixed(1)}`).join(' ')
  return (
    <div className="spice">
      <div className="t">{s.title} · {s.y_label} vs {s.x_label}</div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs><linearGradient id="sg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#3ee7ff" stopOpacity="0.35" /><stop offset="1" stopColor="#3ee7ff" stopOpacity="0" /></linearGradient></defs>
        {[0.25, 0.5, 0.75].map(f => <line key={f} x1={p} x2={W - p} y1={p + f * (H - 2 * p)} y2={p + f * (H - 2 * p)} stroke="rgba(120,150,180,0.15)" />)}
        {right.map((q, i) => <path key={'r' + i} d={path(q, ry0, ry1)} fill="none" stroke="#ffb86b" strokeWidth="1.2" strokeDasharray="3 2" />)}
        {left.map((q, i) => {
          const d = path(q, ly0, ly1)
          return <g key={i}>
            <path d={`${d} L${sx(q.x[q.x.length - 1])},${H - p} L${sx(q.x[0])},${H - p} Z`} fill="url(#sg)" />
            <path d={d} fill="none" stroke="#3ee7ff" strokeWidth="1.5" style={{ filter: 'drop-shadow(0 0 4px #3ee7ff)' }} />
          </g>
        })}
        <text x={p + 2} y={p + 9} fill="#7d8a9b" fontSize="8" fontFamily="JetBrains Mono">{ly1.toFixed(2)} {s.y_label}</text>
        <text x={p + 2} y={H - p - 2} fill="#7d8a9b" fontSize="8" fontFamily="JetBrains Mono">{ly0.toFixed(2)}</text>
        {right.length > 0 && <>
          <text x={W - p - 2} y={p + 9} fill="#ffb86b" fontSize="8" textAnchor="end" fontFamily="JetBrains Mono">{ry1.toFixed(0)} {right[0].name}</text>
          <text x={W - p - 2} y={H - p - 2} fill="#ffb86b" fontSize="8" textAnchor="end" fontFamily="JetBrains Mono">{ry0.toFixed(0)}</text>
        </>}
      </svg>
      {(s.undershoot_mv != null || s.min_v != null) && (
        <div className="chips" style={{ padding: '8px 0 0' }}>
          {s.undershoot_mv != null && <span className="hot">undershoot {fmt(s.undershoot_mv, 1)} mV</span>}
          {s.min_v != null && <span className="hot">min {fmt(s.min_v, 3)} V</span>}
          {s.series.map(q => <span key={q.name} className="hot" style={{ color: q.axis === 'right' ? '#ffb86b' : '#3ee7ff' }}>{q.name}</span>)}
        </div>
      )}
    </div>
  )
}

export function StatsPanel() {
  const components = useStore(s => s.components)
  const nets = useStore(s => s.nets)
  const routing = useStore(s => s.routing)
  const traces = useStore(s => s.traces)
  const vias = useStore(s => s.vias)
  const drc = useStore(s => s.drc)
  const power = useStore(s => s.power)
  const spice = useStore(s => s.spice)
  const artifacts = useStore(s => s.artifacts)
  const stats = useStore(s => s.stats)
  const sel = useStore(s => s.selectedViolation)
  const selectViolation = useStore(s => s.selectViolation)
  const routeFails = useStore(s => s.routeFails)

  const routedPct = stats?.routed_pct ?? (routing.total ? (routing.routed / routing.total) * 100 : 0)
  const errs = drc ? (drc.errors ?? drc.violations.filter(v => v.severity === 'error').length) : 0

  return (
    <div className="panel bracket" style={{ flex: 1 }}>
      <div className="panel-title"><span className="dot" style={{ background: 'var(--cyan)', boxShadow: '0 0 8px var(--cyan)' }} />output<span className="grow" /><span className="tag">jlcpcb 2-layer</span></div>
      <div className="scroll" style={{ flex: 1 }}>
        <div className="tiles">
          <Tile k="components" v={components.length} />
          <Tile k="nets" v={nets.length} />
          <Tile k="routed" v={routedPct} unit="%" tone={routedPct >= 100 ? 'green' : 'cyan'} d={0} />
          <Tile k="vias" v={stats?.vias ?? Math.max(routing.vias, vias.length)} tone="copper" />
          <Tile k="trace length" v={stats?.total_trace_mm ?? routing.length_mm} unit="mm" tone="copper" d={1} />
          <Tile k="segments" v={traces.length} />
        </div>

        <div className="panel-title" style={{ borderTop: '1px solid var(--line)' }}>design rule check<span className="grow" />{drc && <span className="tag">{drc.rules.fab as string}</span>}</div>
        {!drc && <div className="empty">awaiting routing…</div>}
        {drc && drc.passed && errs === 0 && (
          <motion.div className="pass" initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
            ✓ DRC PASS · {drc.checks.reduce((a, c) => a + c.count, 0)} CHECKS{(drc.warnings ?? drc.violations.filter(v => v.severity === 'warning').length) ? ` · ${drc.warnings ?? drc.violations.filter(v => v.severity === 'warning').length} WARNINGS` : ''}
          </motion.div>
        )}
        {drc && (!drc.passed || errs > 0) && (
          <motion.div className="pass" style={{ color: 'var(--magenta)', borderColor: 'rgba(255,79,163,0.4)', background: 'rgba(255,79,163,0.06)' }} initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>✗ DRC FAILED · {errs} ERRORS</motion.div>
        )}
        {drc && (
          <div className="list">
            {drc.checks.map(c => (
              <div className="row" key={c.name}><span className="k">{c.name}</span><span>{c.count} <span className={c.ok ? 'ok' : 'bad'}>{c.ok ? '✓' : '✗'}</span></span></div>
            ))}
            <AnimatePresence>
              {drc.violations.map((v, i) => (
                <motion.div key={i} className={`row viol ${v.severity === 'warning' ? 'warn' : ''} ${sel === v ? 'sel' : ''}`} style={{ display: 'block' }} onClick={() => selectViolation(sel === v ? null : v)} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.03 }}>
                  <div className="code">{v.severity} · {v.code} · {v.layer ?? ''} @ {fmt(v.x)},{fmt(v.y)}</div>
                  <div className="msg">{v.message}</div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
        {routeFails.length > 0 && (
          <div className="list" style={{ paddingTop: 0 }}>
            {routeFails.map((f, i) => <div key={'rf' + i} className="row viol" style={{ display: 'block' }}><div className="code">unrouted · {f.net}</div><div className="msg">{f.reason}</div></div>)}
          </div>
        )}

        {power && (
          <>
            <div className="panel-title" style={{ borderTop: '1px solid var(--line)' }}>power rails · dc drop</div>
            <table className="rails">
              <thead><tr><th>net</th><th>V</th><th>mA</th><th>len</th><th>mΩ</th><th>drop</th></tr></thead>
              <tbody>
                {power.map(r => (
                  <tr key={r.net}><td className="net">{r.net}</td><td>{fmt(r.voltage, 1)}</td><td>{fmtInt(r.current_ma)}</td><td>{fmt(r.length_mm, 0)}</td><td>{fmt(r.resistance_mohm, 1)}</td><td className={r.ok ? 'ok' : 'bad'} style={{ color: r.ok ? 'var(--green)' : 'var(--magenta)' }}>{fmt(r.drop_mv, 1)} mV</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {spice && <><div className="panel-title" style={{ borderTop: '1px solid var(--line)' }}>spice · ngspice</div><SpiceChart s={spice} /></>}

        {artifacts && (
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            <div className="panel-title" style={{ borderTop: '1px solid var(--line)' }}>manufacturing package</div>
            <a className="download" href={artifacts.zip_url} download>⬇ DOWNLOAD PACKAGE (.zip)</a>
            {artifacts.gerber_zip_url && <a className="download small" href={artifacts.gerber_zip_url} download>⬇ GERBERS ONLY · JLCPCB-READY</a>}
            {artifacts.render_url && (
              <a className="render-thumb" href={artifacts.render_url} target="_blank" rel="noreferrer">
                <img src={artifacts.render_url} alt="KiCad render" />
                <div className="cap">RENDERED BY KICAD 10 · click to open</div>
              </a>
            )}
            {artifacts.kicad?.available && (
              <div className="kicad-badge">{artifacts.kicad.drc_passed ? '✓ KICAD VERIFIED · 0 DRC ERRORS' : `KICAD DRC · ${artifacts.kicad.violations ?? '?'} ISSUES`}{artifacts.kicad.unconnected ? ` · ${artifacts.kicad.unconnected} UNCONNECTED` : ''}</div>
            )}
            <div className="files">
              {artifacts.files.map(f => <div key={f.name} className={`file ${f.kind}`}><span className="n" title={f.name}>{f.name.split('/').pop()}</span><span className="kind">{fmtBytes(f.size)}</span></div>)}
            </div>
          </motion.div>
        )}
      </div>
    </div>
  )
}
