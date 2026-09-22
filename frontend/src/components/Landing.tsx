import { api } from '../config'
import { Suspense, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { useStore } from '../store'
import { startLive, startMock, startReplay } from '../ws'
import { MASK_COLORS, type MaskColor } from '../protocol'
import { BoardScene } from '../three/BoardScene'

interface Example { title: string; prompt: string; cached?: boolean }
interface DemoRun { run_id: string; name: string; tagline: string; prompt: string; stats: { components: number; total_trace_mm: number; vias: number; drc_errors: number; kicad_drc_passed?: boolean } }
const FALLBACK: Example[] = [
  { title: 'ESP32 sensor node', prompt: 'A USB-C powered ESP32 environmental sensor node with a temperature/humidity sensor, an RGB status LED, and a reset button. Fits in a small enclosure.' },
  { title: 'Li-ion charger + boost', prompt: 'A single-cell Li-ion battery charger board with USB-C input, a TP4056 charger, battery protection, and a 5 V boost output on a screw terminal.' },
  { title: 'Arduino-style dev board', prompt: 'An ATmega328P development board with a 16 MHz crystal, USB-to-UART bridge, 3.3 V and 5 V rails, an ISP header and all GPIO broken out to headers.' },
  { title: 'Motor driver', prompt: 'A small brushed DC motor driver board for two motors controlled by an ESP32-C3 over Wi-Fi, powered from a 2S LiPo, with a current sensor and reverse polarity protection.' },
]

export function Landing() {
  const prompt = useStore(s => s.prompt); const setPrompt = useStore(s => s.setPrompt)
  const color = useStore(s => s.color); const setColor = useStore(s => s.setColor)
  const [examples, setExamples] = useState<Example[]>(FALLBACK)
  const [health, setHealth] = useState<{ ok: boolean; llm?: string; kicad?: boolean; ngspice?: boolean } | null>(null)
  const [demos, setDemos] = useState<DemoRun[]>([])

  useEffect(() => {
    fetch(api('/api/examples')).then(r => r.ok ? r.json() : Promise.reject()).then((ex: Example[]) => Array.isArray(ex) && ex.length && setExamples(ex)).catch(() => {})
    fetch('/demo/index.json', { cache: 'no-store' }).then(r => r.ok ? r.json() : Promise.reject()).then((d: DemoRun[]) => Array.isArray(d) && setDemos(d)).catch(() => {})
    fetch(api('/api/health')).then(r => r.ok ? r.json() : Promise.reject()).then(h => setHealth({ ok: true, ...h })).catch(() => setHealth({ ok: false }))
  }, [])

  const go = () => { if (prompt.trim()) startLive(prompt.trim(), color) }

  return (
    <div className="landing">
      <div className="landing-canvas">
        <Suspense fallback={null}><BoardScene decor /></Suspense>
      </div>
      <div className="brand-mini">ETCH <span className="v">v0.1 · agentic EDA</span></div>
      <div className="health panel">
        <span className={`led ${health ? (health.ok ? 'ok' : 'bad') : ''}`} />
        <span>{health ? (health.ok ? `ENGINE · ${(health.llm ?? 'llm').toUpperCase()}` : 'ENGINE OFFLINE') : 'ENGINE …'}</span>
        <span className="sep">|</span>
        <span className={`led ${health?.kicad ? 'ok' : ''}`} /><span>KICAD</span>
        <span className="sep">|</span>
        <span className={`led ${health?.ngspice ? 'ok' : ''}`} /><span>SPICE</span>
        {!health?.ok && <><span className="sep">|</span><button className="mini-btn" onClick={() => startMock(color)}>MOCK RUN</button></>}
      </div>

      <div className="hero">
        <motion.div className="hero-eyebrow" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>agentic pcb synthesis</motion.div>
        <motion.h1 initial={{ opacity: 0, y: 20, letterSpacing: '0.1em' }} animate={{ opacity: 1, y: 0, letterSpacing: '-0.04em' }} transition={{ duration: 0.9, ease: [0.2, 0.8, 0.2, 1] }}>ETCH</motion.h1>
        <motion.div className="sub" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.35 }}>
          Describe a device. Get a <b>manufacturable PCB</b> — schematic, placement, routing, DRC, Gerbers.
        </motion.div>

        <motion.div className="prompt-box" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45, duration: 0.6 }}>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go() }}
            placeholder="e.g. A USB-C powered ESP32 sensor node with temperature/humidity, an RGB LED and a battery charger…"
            spellCheck={false}
          />
          <div className="prompt-bar">
            <div className="swatches">
              <span className="lbl">MASK</span>
              {(Object.keys(MASK_COLORS) as MaskColor[]).map(c => (
                <button key={c} className={`swatch ${color === c ? 'on' : ''}`} title={c} style={{ background: MASK_COLORS[c] }} onClick={() => setColor(c)} />
              ))}
            </div>
            <span style={{ color: 'var(--dim)', fontSize: 10, letterSpacing: '0.1em' }}>⌘⏎</span>
            <button className="forge" disabled={!prompt.trim()} onClick={go}>FORGE IT →</button>
          </div>
        </motion.div>

        <motion.div className="examples" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.7 }}>
          {examples.map((ex, i) => (
            <button key={i} className="chip" onClick={() => setPrompt(ex.prompt)} title={ex.prompt}>
              {ex.title}{ex.cached && <span className="cached">● cached</span>}
            </button>
          ))}
        </motion.div>

        {demos.length > 0 && (
          <motion.div className="demos" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.9 }}>
            <div className="demos-label">
              {health && !health.ok ? 'ENGINE OFFLINE · live runs need the backend — replay a recorded run:' : 'OR REPLAY A RECORDED RUN'}
            </div>
            <div className="demos-row">
              {demos.map(d => (
                <button key={d.run_id} className="demo-card" title={d.prompt} onClick={() => { setPrompt(d.prompt); startReplay(d.run_id) }}>
                  <span className="demo-name">▶ {d.name}</span>
                  <span className="demo-tag">{d.tagline}</span>
                  <span className="demo-stats">{d.stats.components} parts · {Math.round(d.stats.total_trace_mm)} mm · {d.stats.vias} vias · {d.stats.drc_errors === 0 ? 'DRC PASS' : `${d.stats.drc_errors} DRC`}{d.stats.kicad_drc_passed ? ' · KiCad ✓' : ''}</span>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </div>
    </div>
  )
}
