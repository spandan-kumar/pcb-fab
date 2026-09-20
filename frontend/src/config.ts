/** Backend origin. Empty = same origin (Vite dev proxy / co-hosted). Set VITE_BACKEND_URL for a remote engine (e.g. an ngrok URL). */
const raw = (import.meta.env.VITE_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? ''
export const API_BASE = raw
export const WS_BASE = raw ? raw.replace(/^http/, 'ws') : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`
export const api = (path: string) => `${API_BASE}${path}`
