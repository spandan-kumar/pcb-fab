import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useStore } from './store'
import { Landing } from './components/Landing'
import { Workspace } from './components/Workspace'
import { startMock, startReplay } from './ws'

export default function App() {
  const phase = useStore(s => s.phase)
  const toast = useStore(s => s.toast)
  const setToast = useStore(s => s.setToast)

  useEffect(() => {
    const q = new URLSearchParams(location.search)
    if (q.get('speed')) useStore.getState().setReplaySpeed(parseFloat(q.get('speed')!) || 1)
    if (q.get('mock')) startMock((q.get('color') as never) || 'black')
    else if (q.get('replay')) startReplay(q.get('replay')!)
  }, [])

  return (
    <div className="scanlines" style={{ height: '100%' }}>
      <div className="bg-grid" />
      <div className="bg-dots" />
      <AnimatePresence mode="wait">
        {phase === 'landing' ? (
          <motion.div key="landing" style={{ height: '100%' }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, scale: 1.03, filter: 'blur(6px)' }} transition={{ duration: 0.45 }}>
            <Landing />
          </motion.div>
        ) : (
          <motion.div key="ws" style={{ height: '100%' }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <Workspace />
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {toast && (
          <motion.div className="toast" initial={{ y: 20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 20, opacity: 0 }}>
            <span>{toast}</span>
            <button onClick={() => setToast(null)}>✕</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
