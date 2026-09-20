// Mirrors /PROTOCOL.md exactly.
export type Stage =
  | 'brief' | 'architect' | 'components' | 'netlist' | 'schematic'
  | 'placement' | 'routing' | 'drc' | 'thermal' | 'power' | 'export'

export const STAGES: Stage[] = [
  'brief', 'architect', 'components', 'netlist', 'schematic',
  'placement', 'routing', 'drc', 'thermal', 'power', 'export',
]

export type Layer = 'F.Cu' | 'B.Cu'
export type MaskColor = 'green' | 'black' | 'purple' | 'blue' | 'red' | 'white'

export interface Pin { num: string; name: string; type: string }
export interface Body { w: number; h: number; z: number; style: string; x?: number; y?: number }

export interface Component {
  ref: string; part_id: string; name: string; value: string
  category: string; description: string; footprint: string; package: string
  lcsc?: string; price_usd?: number; purpose?: string
  pins: Pin[]; body: Body; power_w?: number
}

export interface Net { name: string; cls: string; pins: string[]; voltage?: number; current_ma?: number }

export interface Design {
  name: string; tagline: string; summary: string
  board: { width: number; height: number; corner_radius: number; mounting_holes: boolean; color: MaskColor; layers: number }
  power?: { input: string; rails: string[] }
  estimated_cost_usd?: number
}

export interface Pad {
  num: string; shape: 'rect' | 'roundrect' | 'circle' | 'oval'
  x: number; y: number; w: number; h: number; layer: 'F.Cu' | 'through'; drill?: number
}
export interface Footprint {
  pads: Pad[]
  courtyard: { x: number; y: number; w: number; h: number }
  body: Body
  silk: number[][]
}
export interface BoardText { text: string; x: number; y: number; size: number; layer: string; rot: number }
export interface Board {
  width: number; height: number; corner_radius: number; color: MaskColor
  outline: number[][]
  holes: { x: number; y: number; drill: number; diameter: number }[]
  footprints: Record<string, Footprint>
  texts: BoardText[]
}

export type Positions = Record<string, [number, number, number]>

export interface Trace { net: string; layer: Layer; width: number; points: number[][] }
export interface Via { net: string; x: number; y: number; drill: number; diameter: number }

export interface Violation { code: string; severity: 'error' | 'warning'; message: string; x: number; y: number; layer?: string; refs?: string[] }
export interface Drc {
  passed: boolean
  errors?: number
  warnings?: number
  rules: Record<string, number | string>
  violations: Violation[]
  checks: { name: string; count: number; ok: boolean }[]
}
export interface ThermalFrame {
  frame: number; total: number; cols: number; rows: number; grid: number[]
  min_c: number; max_c: number; hotspots: { ref: string; c: number }[]
}
export interface Rail { net: string; voltage: number; current_ma: number; length_mm: number; width_mm: number; resistance_mohm: number; drop_mv: number; ok: boolean }
export interface SpiceSeries { name: string; x: number[]; y: number[]; axis?: 'left' | 'right' }
export interface Spice { title: string; x_label: string; y_label: string; series: SpiceSeries[]; undershoot_mv?: number; min_v?: number }
export interface Artifacts {
  run_id: string; zip_url: string
  gerber_zip_url?: string
  render_url?: string
  files: { name: string; kind: string; size: number }[]
  kicad?: { available: boolean; drc_passed?: boolean; violations?: number; unconnected?: number }
}
export interface Stats {
  components: number; nets: number; traces: number; vias: number
  total_trace_mm: number; routed_pct: number; drc_errors: number; elapsed_s: number
}

export type Ev =
  | { type: 'status'; stage: Stage; state: 'start' | 'done' | 'error'; message?: string }
  | { type: 'thought'; text: string }
  | { type: 'design'; design: Design }
  | { type: 'component'; component: Component }
  | { type: 'netlist'; nets: Net[] }
  | { type: 'board'; board: Board }
  | { type: 'placement'; iteration: number; total: number; temperature: number; cost: number; positions: Positions }
  | { type: 'placement_final'; positions: Positions }
  | { type: 'ratsnest'; lines: [number, number, number, number, string][] }
  | { type: 'route_begin'; net: string; cls: string }
  | { type: 'trace'; net: string; layer: Layer; width: number; points: number[][] }
  | { type: 'via'; net: string; x: number; y: number; drill: number; diameter: number }
  | { type: 'route_fail'; net: string; reason: string }
  | { type: 'ripup'; net: string; traces?: number; vias?: number }
  | { type: 'reset_routing'; reason?: string }
  | { type: 'run'; run_id: string; prompt?: string; backend?: string; kicad?: boolean; ngspice?: boolean }
  | { type: 'routing_progress'; routed: number; total: number; length_mm: number; vias: number }
  | { type: 'pour'; layer: Layer; net: string; clearance: number; islands_healed?: number; orphans?: number }
  | { type: 'drc'; passed: boolean; rules: Record<string, number | string>; violations: Violation[]; checks: { name: string; count: number; ok: boolean }[]; errors?: number; warnings?: number }
  | { type: 'thermal'; frame: number; total: number; cols: number; rows: number; grid: number[]; min_c: number; max_c: number; hotspots: { ref: string; c: number }[] }
  | { type: 'power'; rails: Rail[] }
  | { type: 'spice'; title: string; x_label: string; y_label: string; series: SpiceSeries[]; undershoot_mv?: number; min_v?: number }
  | { type: 'artifacts'; run_id: string; zip_url: string; files: Artifacts['files']; kicad?: Artifacts['kicad']; gerber_zip_url?: string; render_url?: string }
  | { type: 'done'; stats: Stats }
  | { type: 'error'; message: string }

export type Event = Ev & { seq?: number; t?: number }

export const MASK_COLORS: Record<MaskColor, string> = {
  green: '#1d5c2b', black: '#14161a', purple: '#3b1f5e', blue: '#123a6b', red: '#7a1d22', white: '#d8d8d2',
}
