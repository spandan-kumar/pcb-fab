import { useEffect, useRef, useState } from 'react'
/** Returns a CSS class that flips on for `ms` whenever `value` changes (for value-change micro-pops). */
export function usePop(value: unknown, ms = 420) {
  const [on, setOn] = useState(false)
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    setOn(true)
    const id = window.setTimeout(() => setOn(false), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return on ? 'pop' : ''
}
