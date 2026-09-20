import { useEffect, useRef, useState } from 'react'
/** Smoothly animates a number toward its target. */
export function useCountUp(target: number, ms = 500) {
  const [v, setV] = useState(target)
  const from = useRef(target); const start = useRef(0); const raf = useRef(0)
  useEffect(() => {
    cancelAnimationFrame(raf.current)
    const f0 = v; from.current = f0; start.current = performance.now()
    const tick = () => {
      const k = Math.min(1, (performance.now() - start.current) / ms)
      const e = 1 - Math.pow(1 - k, 3)
      setV(f0 + (target - f0) * e)
      if (k < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])
  return v
}
