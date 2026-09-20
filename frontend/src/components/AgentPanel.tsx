import { useEffect, useMemo, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useStore } from '../store'
import { STAGES } from '../protocol'
import { catColor, fmt } from '../util/format'

function renderMd(text: string) {
  // markdown-lite: **bold**, `code`
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**')) return <b key={i}>{p.slice(2, -2)}</b>
    if (p.startsWith('`') && p.endsWith('`')) return <code key={i} style={{ color: 'var(--cyan)' }}>{p.slice(1, -1)}</code>
    return <span key={i}>{p}</span>
  })
}

export function AgentPanel() {
  const stageStates = useStore(s => s.stageStates)
  const stage = useStore(s => s.stage)
  const stageMessages = useStore(s => s.stageMessages)
  const thoughts = useStore(s => s.thoughts)
  const design = useStore(s => s.design)
  const components = useStore(s => s.components)
  const phase = useStore(s => s.phase)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [thoughts, components.length, design])

  const total = useMemo(() => components.reduce((a, c) => a + (c.price_usd ?? 0), 0), [components])

  return (
    <div className="panel bracket" style={{ flex: 1 }}>
      <div className="panel-title"><span className="dot" />agent<span className="grow" /><span className="tag">{phase === 'running' ? 'thinking' : phase}</span></div>
      <div className="stages">
        {STAGES.map(st => (
          <div key={st} className={`stage ${stageStates[st]}`} title={st}>
            <div className="bar" />
            <div className="nm">{st.slice(0, 5)}</div>
          </div>
        ))}
      </div>
      <div className="stage-msg">
        {stage && stageStates[stage] === 'active' && <span className="spin" />}
        <span>{stage ? (stageMessages[stage] ?? stage) : 'waiting for engine…'}</span>
      </div>
      <div className="scroll" ref={scrollRef} style={{ flex: 1 }}>
        <div className="thoughts">
          {renderMd(thoughts)}
          {phase === 'running' && <span className="caret" />}
        </div>
        {design && (
          <motion.div className="design-card" initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: 'spring', stiffness: 220, damping: 22 }}>
            <div className="name">{design.name}</div>
            <div className="tag">{design.tagline}</div>
            <div className="sum">{design.summary}</div>
            <div className="meta">
              <span>BOARD <b>{fmt(design.board.width, 0)}×{fmt(design.board.height, 0)} mm</b></span>
              <span>LAYERS <b>{design.board.layers}</b></span>
              <span>EST. <b>${fmt(design.estimated_cost_usd ?? total, 2)}</b></span>
            </div>
          </motion.div>
        )}
        {components.length > 0 && (
          <div className="comps">
            <AnimatePresence initial={false}>
              {components.map(c => {
                const col = catColor(c.category)
                return (
                  <motion.div key={c.ref} className="comp" initial={{ opacity: 0, x: -30, rotateX: 20 }} animate={{ opacity: 1, x: 0, rotateX: 0 }} transition={{ type: 'spring', stiffness: 260, damping: 24 }}>
                    <div className="ref" style={{ color: col, borderColor: col + '66', boxShadow: `0 0 12px ${col}33` }}>{c.ref}</div>
                    <div style={{ minWidth: 0 }}>
                      <div className="nm">{c.name}{c.value && <span className="val">{c.value}</span>}</div>
                      <div className="pk">{c.package} · {c.category}</div>
                      {c.purpose && <div className="why">{c.purpose}</div>}
                    </div>
                    <div className="right">
                      {c.price_usd != null && <div className="price">${c.price_usd.toFixed(2)}</div>}
                      {c.lcsc && <div className="lcsc">{c.lcsc}</div>}
                    </div>
                  </motion.div>
                )
              })}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}
