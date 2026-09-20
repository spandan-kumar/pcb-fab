import { create } from 'zustand'
import type {
  Artifacts, Board, Component, Design, Drc, Event, Net, Positions, Rail, Spice, Stage, Stats, ThermalFrame, Trace, Via, Violation, MaskColor,
} from './protocol'
import { STAGES } from './protocol'
import { enqueueTrace, live, scatterInitial, setTargets } from './live'

export type StageState = 'pending' | 'active' | 'done' | 'error'
export type Tab = 'board' | 'schematic' | 'layers' | 'thermal'
export type Phase = 'landing' | 'running' | 'done' | 'error'

export interface RoutingProgress { routed: number; total: number; length_mm: number; vias: number }

export interface State {
  phase: Phase
  prompt: string
  color: MaskColor
  events: Event[]
  stage: Stage | null
  stageStates: Record<Stage, StageState>
  stageMessages: Partial<Record<Stage, string>>
  thoughts: string
  design: Design | null
  components: Component[]
  nets: Net[]
  board: Board | null
  positions: Positions
  placementInfo: { iteration: number; total: number; temperature: number; cost: number } | null
  traces: Trace[]
  vias: Via[]
  ratsnest: [number, number, number, number, string][]
  routedNets: string[]
  routeFails: { net: string; reason: string }[]
  routing: RoutingProgress
  pour: { layer: string; net: string; clearance: number; islands_healed?: number; orphans?: number } | null
  failedNets: string[]
  flash: { text: string; at: number } | null
  runInfo: { backend?: string; kicad?: boolean; ngspice?: boolean } | null
  drc: Drc | null
  thermal: ThermalFrame | null
  power: Rail[] | null
  spice: Spice | null
  artifacts: Artifacts | null
  stats: Stats | null
  error: string | null
  elapsed: number
  hoverNet: string | null
  selectedViolation: Violation | null
  tab: Tab
  userTab: boolean
  exploded: boolean
  layerVis: Record<string, boolean>
  connection: 'idle' | 'connecting' | 'open' | 'closed' | 'error'
  toast: string | null
  replaySpeed: number
  mode: 'live' | 'replay' | 'mock'
  runId: string | null

  applyEvent: (ev: Event) => void
  setTab: (t: Tab, user?: boolean) => void
  setHoverNet: (n: string | null) => void
  selectViolation: (v: Violation | null) => void
  setExploded: (b: boolean) => void
  toggleLayer: (l: string) => void
  setPrompt: (p: string) => void
  setColor: (c: MaskColor) => void
  setPhase: (p: Phase) => void
  setConnection: (c: State['connection']) => void
  setToast: (t: string | null) => void
  setReplaySpeed: (s: number) => void
  setMode: (m: State['mode']) => void
  reset: () => void
}

const initialStages = () => Object.fromEntries(STAGES.map(s => [s, 'pending'])) as Record<Stage, StageState>

const base = () => ({
  events: [] as Event[],
  stage: null as Stage | null,
  stageStates: initialStages(),
  stageMessages: {} as Partial<Record<Stage, string>>,
  thoughts: '',
  design: null as Design | null,
  components: [] as Component[],
  nets: [] as Net[],
  board: null as Board | null,
  positions: {} as Positions,
  placementInfo: null,
  traces: [] as Trace[],
  vias: [] as Via[],
  ratsnest: [] as [number, number, number, number, string][],
  routedNets: [] as string[],
  routeFails: [] as { net: string; reason: string }[],
  failedNets: [] as string[],
  flash: null as { text: string; at: number } | null,
  runInfo: null as { backend?: string; kicad?: boolean; ngspice?: boolean } | null,
  routing: { routed: 0, total: 0, length_mm: 0, vias: 0 },
  pour: null as { layer: string; net: string; clearance: number; islands_healed?: number; orphans?: number } | null,
  drc: null as Drc | null,
  thermal: null as ThermalFrame | null,
  power: null as Rail[] | null,
  spice: null as Spice | null,
  artifacts: null as Artifacts | null,
  stats: null as Stats | null,
  error: null as string | null,
  elapsed: 0,
  hoverNet: null as string | null,
  selectedViolation: null as Violation | null,
  tab: 'board' as Tab,
  userTab: false,
  exploded: false,
  layerVis: { 'F.Cu': true, 'F.Mask': true, 'F.SilkS': true, 'Edge.Cuts': true, 'B.Cu': true, 'Drill': true } as Record<string, boolean>,
  runId: null as string | null,
})

const stageTab: Partial<Record<Stage, Tab>> = {
  schematic: 'schematic', placement: 'board', routing: 'board', drc: 'board', thermal: 'thermal', power: 'board', export: 'board',
}

export const useStore = create<State>((set, get) => ({
  phase: 'landing',
  prompt: '',
  color: 'black',
  connection: 'idle',
  toast: null,
  replaySpeed: 1,
  mode: 'live',
  ...base(),

  applyEvent: (ev) => {
    const s = get()
    const patch: Partial<State> = {}
    const events = s.events.length > 5000 ? s.events.slice(-4000) : s.events.slice()
    events.push(ev)
    patch.events = events
    if (typeof ev.t === 'number') patch.elapsed = ev.t

    switch (ev.type) {
      case 'status': {
        const stageStates = { ...s.stageStates }
        if (ev.state === 'start') {
          stageStates[ev.stage] = 'active'
          // any stage before this one that is still pending -> done (robustness)
          const idx = STAGES.indexOf(ev.stage)
          STAGES.slice(0, idx).forEach(st => { if (stageStates[st] === 'active' || stageStates[st] === 'pending') stageStates[st] = 'done' })
          patch.stage = ev.stage
          if (!s.userTab && stageTab[ev.stage]) patch.tab = stageTab[ev.stage]
          if (ev.stage === 'placement' && !s.userTab) patch.exploded = false
        } else if (ev.state === 'done') {
          stageStates[ev.stage] = 'done'
        } else {
          stageStates[ev.stage] = 'error'
        }
        patch.stageStates = stageStates
        if (ev.message) patch.stageMessages = { ...s.stageMessages, [ev.stage]: ev.message }
        break
      }
      case 'thought':
        patch.thoughts = s.thoughts + ev.text
        break
      case 'design':
        patch.design = ev.design
        if (ev.design.board?.color) patch.color = ev.design.board.color
        break
      case 'component': {
        const comps = s.components.filter(c => c.ref !== ev.component.ref)
        comps.push(ev.component)
        patch.components = comps
        break
      }
      case 'netlist':
        patch.nets = ev.nets
        break
      case 'board': {
        patch.board = ev.board
        if (ev.board.color) patch.color = ev.board.color
        const refs = Object.keys(ev.board.footprints)
        scatterInitial(refs, ev.board.width, ev.board.height)
        patch.positions = {}
        patch.traces = []; patch.vias = []; patch.ratsnest = []; patch.routedNets = []; patch.routeFails = []
        patch.pour = null; patch.drc = null; patch.thermal = null
        live.traceQueue = []; live.lastTraceStart = 0
        break
      }
      case 'placement':
        setTargets(ev.positions, 0.6)
        patch.positions = { ...s.positions, ...ev.positions }
        patch.placementInfo = { iteration: ev.iteration, total: ev.total, temperature: ev.temperature, cost: ev.cost }
        break
      case 'placement_final':
        setTargets(ev.positions, 0)
        live.finalSnap = true
        patch.positions = { ...s.positions, ...ev.positions }
        break
      case 'ratsnest':
        patch.ratsnest = ev.lines
        break
      case 'route_begin':
        if (!s.routedNets.includes(ev.net)) patch.routedNets = [...s.routedNets, ev.net]
        if (s.failedNets.includes(ev.net)) { patch.failedNets = s.failedNets.filter(n => n !== ev.net); patch.routeFails = s.routeFails.filter(f => f.net !== ev.net) }
        break
      case 'trace': {
        const tr: Trace = { net: ev.net, layer: ev.layer, width: ev.width, points: ev.points }
        enqueueTrace(tr)
        patch.traces = [...s.traces, tr]
        break
      }
      case 'via':
        patch.vias = [...s.vias, { net: ev.net, x: ev.x, y: ev.y, drill: ev.drill, diameter: ev.diameter }]
        break
      case 'route_fail':
        patch.routeFails = [...s.routeFails.filter(f => f.net !== ev.net), { net: ev.net, reason: ev.reason }]
        if (!s.failedNets.includes(ev.net)) patch.failedNets = [...s.failedNets, ev.net]
        // bring the airwires back so the failure is visible
        patch.routedNets = s.routedNets.filter(n => n !== ev.net)
        break
      case 'ripup': {
        patch.traces = s.traces.filter(t => t.net !== ev.net)
        patch.vias = s.vias.filter(v => v.net !== ev.net)
        patch.routedNets = s.routedNets.filter(n => n !== ev.net)
        patch.failedNets = s.failedNets.filter(n => n !== ev.net)
        patch.routeFails = s.routeFails.filter(f => f.net !== ev.net)
        patch.flash = { text: `rip-up: ${ev.net}`, at: performance.now() }
        live.traceQueue = live.traceQueue.filter(q => q.trace.net !== ev.net)
        break
      }
      case 'reset_routing':
        patch.traces = []; patch.vias = []; patch.pour = null; patch.routedNets = []; patch.failedNets = []; patch.routeFails = []
        patch.drc = null; patch.routing = { routed: 0, total: 0, length_mm: 0, vias: 0 }
        patch.flash = { text: `routing reset${ev.reason ? ` · ${ev.reason}` : ''}`, at: performance.now() }
        live.traceQueue = []; live.lastTraceStart = 0; live.finalSnap = false; live.landed.clear()
        break
      case 'run':
        patch.runId = ev.run_id
        patch.runInfo = { backend: ev.backend, kicad: ev.kicad, ngspice: ev.ngspice }
        if (ev.prompt && !s.prompt) patch.prompt = ev.prompt
        break
      case 'routing_progress':
        patch.routing = { routed: ev.routed, total: ev.total, length_mm: ev.length_mm, vias: ev.vias }
        break
      case 'pour':
        patch.pour = { layer: ev.layer, net: ev.net, clearance: ev.clearance, islands_healed: ev.islands_healed, orphans: ev.orphans }
        break
      case 'drc':
        patch.drc = { passed: ev.passed, rules: ev.rules, violations: ev.violations, checks: ev.checks, errors: ev.errors, warnings: ev.warnings }
        break
      case 'thermal':
        patch.thermal = { frame: ev.frame, total: ev.total, cols: ev.cols, rows: ev.rows, grid: ev.grid, min_c: ev.min_c, max_c: ev.max_c, hotspots: ev.hotspots }
        break
      case 'power':
        patch.power = ev.rails
        break
      case 'spice':
        patch.spice = { title: ev.title, x_label: ev.x_label, y_label: ev.y_label, series: ev.series, undershoot_mv: ev.undershoot_mv, min_v: ev.min_v }
        break
      case 'artifacts':
        patch.artifacts = { run_id: ev.run_id, zip_url: ev.zip_url, files: ev.files, kicad: ev.kicad, gerber_zip_url: ev.gerber_zip_url, render_url: ev.render_url }
        patch.runId = ev.run_id
        break
      case 'done': {
        patch.stats = ev.stats
        patch.phase = 'done'
        const stageStates = { ...s.stageStates }
        STAGES.forEach(st => { if (stageStates[st] !== 'error') stageStates[st] = 'done' })
        patch.stageStates = stageStates
        if (!s.userTab) patch.tab = 'board'
        break
      }
      case 'error':
        patch.error = ev.message
        patch.phase = 'error'
        patch.toast = ev.message
        break
    }
    set(patch)
  },

  setTab: (tab, user = true) => set({ tab, userTab: user ? true : get().userTab, exploded: tab === 'layers' }),
  setHoverNet: (hoverNet) => set({ hoverNet }),
  selectViolation: (v) => {
    if (v) live.camTarget = { x: v.x, y: v.y, at: performance.now() }
    set({ selectedViolation: v })
  },
  setExploded: (exploded) => set({ exploded }),
  toggleLayer: (l) => set({ layerVis: { ...get().layerVis, [l]: !get().layerVis[l] } }),
  setPrompt: (prompt) => set({ prompt }),
  setColor: (color) => set({ color }),
  setPhase: (phase) => set({ phase }),
  setConnection: (connection) => set({ connection }),
  setToast: (toast) => set({ toast }),
  setReplaySpeed: (replaySpeed) => set({ replaySpeed }),
  setMode: (mode) => set({ mode }),
  reset: () => {
    live.traceQueue = []; live.lastTraceStart = 0
    live.targets.clear(); live.current.clear(); live.landed.clear(); live.finalSnap = false
    set({ ...base(), phase: 'running', error: null, toast: null })
  },
}))

// debug handle
;(window as unknown as { __etch: unknown }).__etch = useStore
