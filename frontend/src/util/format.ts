export const fmt = (n: number, d = 1) => (Number.isFinite(n) ? n.toFixed(d) : '—')
export const fmtInt = (n: number) => (Number.isFinite(n) ? Math.round(n).toLocaleString() : '—')
export const fmtBytes = (b: number) => (b > 1024 * 1024 ? `${(b / 1048576).toFixed(1)} MB` : b > 1024 ? `${(b / 1024).toFixed(1)} KB` : `${b} B`)
export const fmtTime = (s: number) => { const m = Math.floor(s / 60); const r = s - m * 60; return m ? `${m}:${r.toFixed(0).padStart(2, '0')}` : `${r.toFixed(1)}s` }

export const CATEGORY_COLORS: Record<string, string> = {
  mcu: '#3ee7ff', power: '#ffcf5a', passive: '#9aa7b8', connector: '#c0c8d4', sensor: '#7cff5a', led: '#ff7ad9',
  switch: '#b48cff', ic: '#5ab6ff', crystal: '#d8d8d2', module: '#3ee7ff', mechanical: '#6b7684', protection: '#ff9d5a',
}
export const catColor = (c: string) => CATEGORY_COLORS[c] ?? '#9aa7b8'
