// Synthetic event sequence so the UI can be developed/demoed without the backend (?mock=1).
import type { Board, Component, Ev, Event, Footprint, MaskColor, Net, Pad, Positions, Stage } from '../protocol'

const W = 40, H = 30

function chip(l: number, w: number, gap: number): Footprint {
  const pads: Pad[] = [
    { num: '1', shape: 'roundrect', x: -(gap / 2 + w / 2), y: 0, w, h: l, layer: 'F.Cu' },
    { num: '2', shape: 'roundrect', x: gap / 2 + w / 2, y: 0, w, h: l, layer: 'F.Cu' },
  ]
  const bw = gap + 2 * w + 0.3, bh = l + 0.3
  return { pads, courtyard: { x: -bw / 2, y: -bh / 2, w: bw, h: bh }, body: { x: -(gap + 0.6) / 2, y: -l / 2 + 0.15, w: gap + 0.6, h: l - 0.3, z: 0.45, style: 'passive' }, silk: [] }
}
const c0603 = () => chip(0.9, 0.9, 0.9)

function sot23(n: 5 | 6): Footprint {
  const pads: Pad[] = []
  const pitch = 0.95
  for (let i = 0; i < 3; i++) pads.push({ num: String(i + 1), shape: 'roundrect', x: (i - 1) * pitch, y: -1.1, w: 0.6, h: 1.1, layer: 'F.Cu' })
  if (n === 5) { pads.push({ num: '4', shape: 'roundrect', x: pitch, y: 1.1, w: 0.6, h: 1.1, layer: 'F.Cu' }); pads.push({ num: '5', shape: 'roundrect', x: -pitch, y: 1.1, w: 0.6, h: 1.1, layer: 'F.Cu' }) }
  else for (let i = 0; i < 3; i++) pads.push({ num: String(6 - i), shape: 'roundrect', x: (i - 1) * pitch, y: 1.1, w: 0.6, h: 1.1, layer: 'F.Cu' })
  return { pads, courtyard: { x: -1.9, y: -1.9, w: 3.8, h: 3.8 }, body: { x: -1.5, y: -0.8, w: 3.0, h: 1.6, z: 1.1, style: 'sot' }, silk: [[-1.5, -0.8, 1.5, -0.8], [-1.5, 0.8, 1.5, 0.8]] }
}

function dfn8(): Footprint {
  const pads: Pad[] = []
  for (let i = 0; i < 4; i++) {
    pads.push({ num: String(i + 1), shape: 'rect', x: -1.05, y: (1.5 - i) * 0.5 - 0.25 + 0.25, w: 0.65, h: 0.3, layer: 'F.Cu' })
    pads.push({ num: String(8 - i), shape: 'rect', x: 1.05, y: (1.5 - i) * 0.5, w: 0.65, h: 0.3, layer: 'F.Cu' })
  }
  pads[0].y = 0.75; pads[2].y = 0.25; pads[4].y = -0.25; pads[6].y = -0.75
  return { pads, courtyard: { x: -1.7, y: -1.5, w: 3.4, h: 3.0 }, body: { x: -1.25, y: -1.25, w: 2.5, h: 2.5, z: 0.9, style: 'chip' }, silk: [] }
}

function moduleEsp(): Footprint {
  const pads: Pad[] = []
  const bw = 13.2, bh = 16.6
  let n = 1
  for (let i = 0; i < 9; i++) { pads.push({ num: String(n++), shape: 'rect', x: -bw / 2 + 0.4, y: 5.6 - i * 1.4, w: 0.9, h: 0.8, layer: 'F.Cu' }) }
  for (let i = 0; i < 8; i++) { pads.push({ num: String(n++), shape: 'rect', x: -5.6 + i * 1.4 + 0.7, y: -bh / 2 + 0.4, w: 0.8, h: 0.9, layer: 'F.Cu' }) }
  for (let i = 0; i < 9; i++) { pads.push({ num: String(n++), shape: 'rect', x: bw / 2 - 0.4, y: -5.6 + i * 1.4, w: 0.9, h: 0.8, layer: 'F.Cu' }) }
  return {
    pads, courtyard: { x: -bw / 2 - 0.5, y: -bh / 2 - 0.5, w: bw + 1, h: bh + 1 },
    body: { x: -bw / 2, y: -bh / 2, w: bw, h: bh, z: 2.4, style: 'module' },
    silk: [[-bw / 2, -bh / 2, bw / 2, -bh / 2], [bw / 2, -bh / 2, bw / 2, bh / 2], [bw / 2, bh / 2, -bw / 2, bh / 2], [-bw / 2, bh / 2, -bw / 2, -bh / 2]],
  }
}

function usbC(): Footprint {
  const pads: Pad[] = []
  const names = ['A1', 'A4', 'A5', 'A6', 'A7', 'A8', 'A9', 'A12']
  names.forEach((nm, i) => pads.push({ num: nm, shape: 'roundrect', x: -3.5 + i * 1.0, y: 2.5, w: 0.6, h: 1.2, layer: 'F.Cu' }))
  const names2 = ['B12', 'B9', 'B8', 'B7', 'B6', 'B5', 'B4', 'B1']
  names2.forEach((nm, i) => pads.push({ num: nm, shape: 'roundrect', x: -3.5 + i * 1.0, y: 3.9, w: 0.6, h: 0.9, layer: 'F.Cu' }))
  pads.push({ num: 'S1', shape: 'oval', x: -4.32, y: 3.0, w: 1.0, h: 1.8, layer: 'through', drill: 0.6 })
  pads.push({ num: 'S2', shape: 'oval', x: 4.32, y: 3.0, w: 1.0, h: 1.8, layer: 'through', drill: 0.6 })
  pads.push({ num: 'S3', shape: 'oval', x: -4.32, y: -1.2, w: 1.0, h: 1.8, layer: 'through', drill: 0.6 })
  pads.push({ num: 'S4', shape: 'oval', x: 4.32, y: -1.2, w: 1.0, h: 1.8, layer: 'through', drill: 0.6 })
  return { pads, courtyard: { x: -5, y: -4.5, w: 10, h: 9.5 }, body: { x: -4.5, y: -4.2, w: 9.0, h: 7.4, z: 3.2, style: 'usb' }, silk: [] }
}

function tact(): Footprint {
  const pads: Pad[] = [
    { num: '1', shape: 'rect', x: -3.2, y: 2.2, w: 1.6, h: 1.2, layer: 'F.Cu' },
    { num: '2', shape: 'rect', x: 3.2, y: 2.2, w: 1.6, h: 1.2, layer: 'F.Cu' },
    { num: '3', shape: 'rect', x: -3.2, y: -2.2, w: 1.6, h: 1.2, layer: 'F.Cu' },
    { num: '4', shape: 'rect', x: 3.2, y: -2.2, w: 1.6, h: 1.2, layer: 'F.Cu' },
  ]
  return { pads, courtyard: { x: -4.3, y: -3.2, w: 8.6, h: 6.4 }, body: { x: -3, y: -3, w: 6, h: 6, z: 3.5, style: 'switch' }, silk: [] }
}

const comps: Component[] = [
  { ref: 'U1', part_id: 'esp32-c3-mini-1', name: 'ESP32-C3-MINI-1', value: '', category: 'mcu', description: 'RISC-V Wi-Fi + BLE 5 module', footprint: 'ESP32-C3-MINI-1', package: 'Module 13.2×16.6 mm', lcsc: 'C2934560', price_usd: 1.9, purpose: 'Main controller with Wi-Fi/BLE.', pins: [{ num: '1', name: 'GND', type: 'gnd' }, { num: '3', name: '3V3', type: 'power_in' }, { num: '5', name: 'IO2', type: 'bidirectional' }, { num: '6', name: 'IO3', type: 'bidirectional' }, { num: '8', name: 'EN', type: 'input' }, { num: '12', name: 'IO8', type: 'bidirectional' }, { num: '13', name: 'IO9', type: 'bidirectional' }, { num: '18', name: 'IO18', type: 'bidirectional' }, { num: '19', name: 'IO19', type: 'bidirectional' }], body: { w: 13.2, h: 16.6, z: 2.4, style: 'module' }, power_w: 0.6 },
  { ref: 'U2', part_id: 'ap2112k-3.3', name: 'AP2112K-3.3', value: '3.3V 600mA', category: 'power', description: 'LDO regulator', footprint: 'SOT-23-5', package: 'SOT-23-5', lcsc: 'C51118', price_usd: 0.12, purpose: 'Regulates USB 5 V to 3.3 V.', pins: [{ num: '1', name: 'VIN', type: 'power_in' }, { num: '2', name: 'GND', type: 'gnd' }, { num: '3', name: 'EN', type: 'input' }, { num: '4', name: 'NC', type: 'nc' }, { num: '5', name: 'VOUT', type: 'power_out' }], body: { w: 3, h: 1.6, z: 1.1, style: 'sot' }, power_w: 0.9 },
  { ref: 'U3', part_id: 'sht31', name: 'SHT31-DIS', value: '', category: 'sensor', description: 'Temp/humidity sensor, I²C', footprint: 'DFN-8', package: 'DFN-8 2.5×2.5', lcsc: 'C93241', price_usd: 2.1, purpose: 'Environmental sensing.', pins: [{ num: '1', name: 'SDA', type: 'bidirectional' }, { num: '2', name: 'ADDR', type: 'input' }, { num: '3', name: 'ALERT', type: 'output' }, { num: '4', name: 'SCL', type: 'input' }, { num: '5', name: 'VDD', type: 'power_in' }, { num: '6', name: 'nRESET', type: 'input' }, { num: '7', name: 'R', type: 'nc' }, { num: '8', name: 'VSS', type: 'gnd' }], body: { w: 2.5, h: 2.5, z: 0.9, style: 'chip' }, power_w: 0.01 },
  { ref: 'J1', part_id: 'usb-c-16p', name: 'USB-C 16P', value: '', category: 'connector', description: 'USB Type-C receptacle, USB 2.0', footprint: 'USB-C-16P', package: 'SMD+THT', lcsc: 'C165948', price_usd: 0.35, purpose: 'Power and programming.', pins: [{ num: 'A1', name: 'GND', type: 'gnd' }, { num: 'A4', name: 'VBUS', type: 'power_out' }, { num: 'A5', name: 'CC1', type: 'passive' }, { num: 'A6', name: 'D+', type: 'bidirectional' }, { num: 'A7', name: 'D-', type: 'bidirectional' }, { num: 'B5', name: 'CC2', type: 'passive' }], body: { w: 9, h: 7.4, z: 3.2, style: 'usb' } },
  { ref: 'C1', part_id: 'cap-0603', name: 'Capacitor', value: '10µF', category: 'passive', description: 'MLCC 0603', footprint: 'C_0603', package: '0603', lcsc: 'C19702', price_usd: 0.02, purpose: 'LDO input decoupling.', pins: [{ num: '1', name: '1', type: 'passive' }, { num: '2', name: '2', type: 'passive' }], body: { w: 1.6, h: 0.8, z: 0.45, style: 'passive' } },
  { ref: 'C2', part_id: 'cap-0603', name: 'Capacitor', value: '10µF', category: 'passive', description: 'MLCC 0603', footprint: 'C_0603', package: '0603', lcsc: 'C19702', price_usd: 0.02, purpose: 'LDO output decoupling.', pins: [{ num: '1', name: '1', type: 'passive' }, { num: '2', name: '2', type: 'passive' }], body: { w: 1.6, h: 0.8, z: 0.45, style: 'passive' } },
  { ref: 'C3', part_id: 'cap-0603', name: 'Capacitor', value: '100nF', category: 'passive', description: 'MLCC 0603', footprint: 'C_0603', package: '0603', lcsc: 'C14663', price_usd: 0.01, purpose: 'Sensor decoupling.', pins: [{ num: '1', name: '1', type: 'passive' }, { num: '2', name: '2', type: 'passive' }], body: { w: 1.6, h: 0.8, z: 0.45, style: 'passive' } },
  { ref: 'R1', part_id: 'res-0603', name: 'Resistor', value: '5.1kΩ', category: 'passive', description: 'CC pulldown', footprint: 'R_0603', package: '0603', lcsc: 'C23186', price_usd: 0.01, purpose: 'USB-C CC1 pulldown (sink).', pins: [{ num: '1', name: '1', type: 'passive' }, { num: '2', name: '2', type: 'passive' }], body: { w: 1.6, h: 0.8, z: 0.45, style: 'passive' } },
  { ref: 'R2', part_id: 'res-0603', name: 'Resistor', value: '1kΩ', category: 'passive', description: 'LED series', footprint: 'R_0603', package: '0603', lcsc: 'C21190', price_usd: 0.01, purpose: 'LED current limit.', pins: [{ num: '1', name: '1', type: 'passive' }, { num: '2', name: '2', type: 'passive' }], body: { w: 1.6, h: 0.8, z: 0.45, style: 'passive' } },
  { ref: 'D1', part_id: 'led-0603', name: 'LED', value: 'Cyan', category: 'led', description: 'Status LED 0603', footprint: 'LED_0603', package: '0603', lcsc: 'C72041', price_usd: 0.03, purpose: 'Status indicator.', pins: [{ num: '1', name: 'K', type: 'passive' }, { num: '2', name: 'A', type: 'passive' }], body: { w: 1.6, h: 0.8, z: 0.6, style: 'led' } },
  { ref: 'SW1', part_id: 'tact-6x6', name: 'Tactile switch', value: 'RESET', category: 'switch', description: '6×6 mm tact', footprint: 'SW_6x6', package: 'SMD 6×6', lcsc: 'C318884', price_usd: 0.05, purpose: 'Reset button.', pins: [{ num: '1', name: '1', type: 'passive' }, { num: '2', name: '2', type: 'passive' }, { num: '3', name: '3', type: 'passive' }, { num: '4', name: '4', type: 'passive' }], body: { w: 6, h: 6, z: 3.5, style: 'switch' } },
]

const fps: Record<string, Footprint> = {
  U1: moduleEsp(), U2: sot23(5), U3: dfn8(), J1: usbC(), C1: c0603(), C2: c0603(), C3: c0603(), R1: c0603(), R2: c0603(), D1: c0603(), SW1: tact(),
}

const nets: Net[] = [
  { name: 'GND', cls: 'gnd', pins: ['U1.1', 'U2.2', 'U3.8', 'J1.A1', 'C1.2', 'C2.2', 'C3.2', 'D1.1', 'R1.2', 'SW1.3', 'SW1.4'] },
  { name: 'VBUS', cls: 'power', pins: ['J1.A4', 'U2.1', 'C1.1'], voltage: 5, current_ma: 500 },
  { name: '3V3', cls: 'power', pins: ['U2.5', 'C2.1', 'U1.3', 'U3.5', 'C3.1', 'U2.3'], voltage: 3.3, current_ma: 400 },
  { name: 'SDA', cls: 'signal', pins: ['U1.12', 'U3.1'] },
  { name: 'SCL', cls: 'signal', pins: ['U1.13', 'U3.4'] },
  { name: 'USB_D+', cls: 'highspeed', pins: ['J1.A6', 'U1.19'] },
  { name: 'USB_D-', cls: 'highspeed', pins: ['J1.A7', 'U1.18'] },
  { name: 'CC1', cls: 'signal', pins: ['J1.A5', 'R1.1'] },
  { name: 'LED', cls: 'signal', pins: ['U1.5', 'R2.1'] },
  { name: 'LED_K', cls: 'signal', pins: ['R2.2', 'D1.2'] },
  { name: 'EN', cls: 'signal', pins: ['U1.8', 'SW1.1', 'SW1.2'] },
  { name: 'ALERT', cls: 'signal', pins: ['U3.3', 'U1.6'] },
]

const finalPos: Positions = {
  U1: [13, 15, 0], U2: [27, 8, 0], U3: [33, 22, 0], J1: [33, 5, 180], C1: [23, 5.5, 90], C2: [31, 12, 90], C3: [30, 26, 0], R1: [24.5, 12, 90], R2: [23, 24, 0], D1: [23, 27.5, 0], SW1: [8, 5.5, 0],
}

function rot(x: number, y: number, deg: number): [number, number] {
  const r = (deg * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r)
  return [x * c - y * s, x * s + y * c]
}
function padPos(ref: string, num: string): [number, number] {
  const fp = fps[ref]; const p = fp.pads.find(p => p.num === num)!
  const [x, y, r] = finalPos[ref]
  const [dx, dy] = rot(p.x, p.y, r)
  return [+(x + dx).toFixed(3), +(y + dy).toFixed(3)]
}

export function generateMockRun(color: MaskColor = 'black'): Event[] {
  const ev: Event[] = []
  let seq = 0
  const push = (t: number, e: Ev) => ev.push({ ...(e as Event), seq: seq++, t: +t.toFixed(3) })
  let t = 0
  const status = (stage: Stage, state: 'start' | 'done', message?: string) => push(t, { type: 'status', stage, state, message })

  status('brief', 'start', 'Reading your brief'); t += 0.4
  push(t, { type: 'thought', text: '**Brief.** A compact USB-C powered environmental sensor node. ' }); t += 0.3
  push(t, { type: 'thought', text: 'Needs Wi-Fi, I²C temperature/humidity sensing, a status LED and a reset button.\n\n' }); t += 0.3
  status('brief', 'done'); status('architect', 'start', 'Choosing an architecture')
  const arch = 'Picking the **ESP32-C3-MINI-1**: RISC-V, native USB-serial (no bridge chip), tiny footprint. Power: USB VBUS → **AP2112K-3.3** LDO (600 mA, low dropout). Sensor: **SHT31** on I²C. USB-C needs 5.1 kΩ CC pulldown to negotiate 5 V as a sink.\n\nBoard estimate: 40 × 30 mm, 2 layers, bottom GND pour.\n\n'
  for (const chunk of arch.match(/.{1,28}/g) ?? []) { t += 0.07; push(t, { type: 'thought', text: chunk }) }
  push(t, { type: 'design', design: { name: 'AirNode Mini', tagline: 'USB-C ESP32-C3 environmental sensor', summary: 'A 40×30 mm two-layer board with an ESP32-C3 module, SHT31 sensor, USB-C input and LDO regulation.', board: { width: W, height: H, corner_radius: 2, mounting_holes: true, color, layers: 2 }, power: { input: 'USB-C 5 V', rails: ['3V3'] }, estimated_cost_usd: 4.8 } })
  status('architect', 'done'); status('components', 'start', 'Selecting 11 parts')
  for (const c of comps) { t += 0.35; push(t, { type: 'component', component: c }) }
  status('components', 'done'); t += 0.2
  status('netlist', 'start', 'Wiring 12 nets'); t += 0.4
  push(t, { type: 'netlist', nets }); status('netlist', 'done')
  status('schematic', 'start', 'Laying out schematic'); t += 2.5; status('schematic', 'done')

  // board
  const board: Board = {
    width: W, height: H, corner_radius: 2, color,
    outline: [[0, 0], [W, 0], [W, H], [0, H]],
    holes: [{ x: 3, y: 27, drill: 2.2, diameter: 4.4 }, { x: 37, y: 27, drill: 2.2, diameter: 4.4 }],
    footprints: fps,
    texts: [{ text: 'AIRNODE MINI v1', x: 20, y: 29.0, size: 1.0, layer: 'F.SilkS', rot: 0 }, { text: 'ETCH', x: 37, y: 1.5, size: 0.8, layer: 'F.SilkS', rot: 0 }],
  }
  status('placement', 'start', 'Annealing placement'); t += 0.1
  push(t, { type: 'board', board })
  // placement frames: converge from random toward final
  const seeds: Positions = {}
  Object.keys(finalPos).forEach((r, i) => { seeds[r] = [((i * 13) % 37) + 2, ((i * 29) % 27) + 2, ((i * 7) % 4) * 90] })
  const frames = 48
  for (let f = 0; f <= frames; f++) {
    t += 0.06
    const k = f / frames
    const ease = 1 - Math.pow(1 - k, 3)
    const positions: Positions = {}
    for (const r of Object.keys(finalPos)) {
      const [sx, sy] = seeds[r]; const [fx, fy, fr] = finalPos[r]
      const jitter = (1 - ease) * 6
      const jx = Math.sin(f * 1.7 + r.length) * jitter, jy = Math.cos(f * 2.3 + r.charCodeAt(0)) * jitter
      positions[r] = [+(sx + (fx - sx) * ease + jx).toFixed(2), +(sy + (fy - sy) * ease + jy).toFixed(2), f < frames * 0.7 ? seeds[r][2] : fr]
    }
    push(t, { type: 'placement', iteration: f * 160, total: frames * 160, temperature: +(40 * (1 - k)).toFixed(2), cost: +(900 * (1 - ease) + 210).toFixed(1), positions })
  }
  t += 0.2
  push(t, { type: 'placement_final', positions: finalPos })
  // ratsnest
  const lines: [number, number, number, number, string][] = []
  for (const n of nets) {
    if (n.cls === 'gnd') continue
    const pts = n.pins.map(p => { const [r, num] = p.split('.'); return padPos(r, num) })
    for (let i = 1; i < pts.length; i++) lines.push([pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], n.name])
  }
  push(t, { type: 'ratsnest', lines })
  status('placement', 'done'); t += 0.4

  // routing
  status('routing', 'start', 'Routing 12 nets')
  let routed = 0, len = 0, vias = 0
  const order = nets.filter(n => n.cls !== 'gnd')
  for (const n of order) {
    t += 0.15
    push(t, { type: 'route_begin', net: n.name, cls: n.cls })
    const width = n.cls === 'power' ? 0.5 : 0.25
    const pts = n.pins.map(p => { const [r, num] = p.split('.'); return padPos(r, num) })
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i]
      const useVia = (i + n.name.length) % 3 === 0 && Math.hypot(b[0] - a[0], b[1] - a[1]) > 8
      if (!useVia) {
        const mid: [number, number] = [b[0], a[1]]
        const dx = Math.abs(b[0] - a[0]), dy = Math.abs(b[1] - a[1])
        const points = dx > 0.6 && dy > 0.6
          ? [a, [a[0] + Math.sign(b[0] - a[0]) * Math.min(dx, dy) * 0.5, a[1] + Math.sign(b[1] - a[1]) * Math.min(dx, dy) * 0.5], mid[0] === b[0] ? [b[0], a[1] + Math.sign(b[1] - a[1]) * Math.min(dx, dy) * 0.5] : mid, b]
          : [a, b]
        t += 0.12
        push(t, { type: 'trace', net: n.name, layer: 'F.Cu', width, points })
        len += Math.hypot(b[0] - a[0], b[1] - a[1])
      } else {
        const v1: [number, number] = [a[0], a[1] + 1.5], v2: [number, number] = [b[0], b[1] - 1.5]
        t += 0.1; push(t, { type: 'trace', net: n.name, layer: 'F.Cu', width, points: [a, v1] })
        push(t, { type: 'via', net: n.name, x: v1[0], y: v1[1], drill: 0.3, diameter: 0.6 })
        t += 0.12; push(t, { type: 'trace', net: n.name, layer: 'B.Cu', width, points: [v1, [v1[0], (v1[1] + v2[1]) / 2], [v2[0], (v1[1] + v2[1]) / 2], v2] })
        push(t, { type: 'via', net: n.name, x: v2[0], y: v2[1], drill: 0.3, diameter: 0.6 })
        t += 0.1; push(t, { type: 'trace', net: n.name, layer: 'F.Cu', width, points: [v2, b] })
        vias += 2; len += Math.hypot(b[0] - a[0], b[1] - a[1]) + 3
      }
    }
    routed++
    push(t, { type: 'routing_progress', routed, total: order.length + 1, length_mm: +len.toFixed(1), vias })
  }
  // GND: stub + via per pin
  t += 0.15
  push(t, { type: 'route_begin', net: 'GND', cls: 'gnd' })
  for (const p of nets[0].pins) {
    const [r, num] = p.split('.'); const a = padPos(r, num)
    const v: [number, number] = [a[0], a[1] - 1.2]
    t += 0.05
    push(t, { type: 'trace', net: 'GND', layer: 'F.Cu', width: 0.3, points: [a, v] })
    push(t, { type: 'via', net: 'GND', x: v[0], y: v[1], drill: 0.3, diameter: 0.6 })
    vias++
  }
  routed++
  push(t, { type: 'pour', layer: 'B.Cu', net: 'GND', clearance: 0.3 })
  push(t, { type: 'routing_progress', routed, total: order.length + 1, length_mm: +len.toFixed(1), vias })
  status('routing', 'done'); t += 0.3

  status('drc', 'start', 'Checking against JLCPCB rules'); t += 0.9
  push(t, { type: 'drc', passed: true, rules: { min_trace_mm: 0.127, min_clearance_mm: 0.127, min_drill_mm: 0.3, min_annular_mm: 0.13, fab: 'JLCPCB 2-layer' }, violations: [], checks: [{ name: 'Clearance', count: 184, ok: true }, { name: 'Trace width', count: 31, ok: true }, { name: 'Annular ring', count: 17, ok: true }, { name: 'Drill size', count: 19, ok: true }, { name: 'Courtyard overlap', count: 11, ok: true }, { name: 'Connectivity', count: 12, ok: true }] })
  status('drc', 'done'); t += 0.2

  status('thermal', 'start', 'Solving steady-state heat')
  const cols = W, rows = H
  const heat = [{ x: 27, y: 8, p: 0.9 }, { x: 13, y: 15, p: 0.6 }]
  for (let f = 1; f <= 24; f++) {
    t += 0.12
    const grid: number[] = new Array(cols * rows)
    const spread = 1.5 + f * 0.35
    let mx = 25
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      let v = 25
      for (const h of heat) { const d2 = (c + 0.5 - h.x) ** 2 + (r + 0.5 - h.y) ** 2; v += h.p * 28 * Math.exp(-d2 / (2 * spread * spread)) * Math.min(1, f / 10) }
      grid[r * cols + c] = +v.toFixed(2); if (v > mx) mx = v
    }
    push(t, { type: 'thermal', frame: f, total: 24, cols, rows, grid, min_c: 25, max_c: +mx.toFixed(1), hotspots: [{ ref: 'U2', c: +mx.toFixed(1) }, { ref: 'U1', c: +(25 + 0.6 * 28 * Math.min(1, f / 10)).toFixed(1) }] })
  }
  status('thermal', 'done'); t += 0.2
  status('power', 'start', 'DC analysis'); t += 0.5
  push(t, { type: 'power', rails: [{ net: 'VBUS', voltage: 5, current_ma: 500, length_mm: 9.4, width_mm: 0.5, resistance_mohm: 9.2, drop_mv: 4.6, ok: true }, { net: '3V3', voltage: 3.3, current_ma: 400, length_mm: 24.1, width_mm: 0.5, resistance_mohm: 23.7, drop_mv: 9.5, ok: true }] })
  push(t, { type: 'spice', title: '3V3 rail load step (0→400 mA)', x_label: 't (ms)', y_label: 'V', series: [{ name: 'V(3V3)', x: Array.from({ length: 80 }, (_, i) => i * 0.05), y: Array.from({ length: 80 }, (_, i) => { const tt = i * 0.05; return tt < 1 ? 3.3 : +(3.3 - 0.09 * Math.exp(-(tt - 1) / 0.25) * Math.cos((tt - 1) * 12)).toFixed(4) }) }] })
  status('power', 'done'); t += 0.2
  status('export', 'start', 'Writing Gerbers, drill, BOM, KiCad'); t += 1.4
  push(t, { type: 'artifacts', run_id: 'mock', zip_url: '#', files: [{ name: 'AirNodeMini-F_Cu.gtl', kind: 'gerber', size: 18233 }, { name: 'AirNodeMini-B_Cu.gbl', kind: 'gerber', size: 12100 }, { name: 'AirNodeMini-F_Mask.gts', kind: 'gerber', size: 5100 }, { name: 'AirNodeMini-B_Mask.gbs', kind: 'gerber', size: 2100 }, { name: 'AirNodeMini-F_SilkS.gto', kind: 'gerber', size: 9800 }, { name: 'AirNodeMini-Edge_Cuts.gm1', kind: 'gerber', size: 600 }, { name: 'AirNodeMini.drl', kind: 'drill', size: 900 }, { name: 'AirNodeMini.kicad_pcb', kind: 'kicad', size: 50123 }, { name: 'bom.csv', kind: 'bom', size: 900 }, { name: 'cpl.csv', kind: 'cpl', size: 700 }], kicad: { available: true, drc_passed: true, violations: 0, unconnected: 0 } })
  status('export', 'done'); t += 0.3
  push(t, { type: 'done', stats: { components: comps.length, nets: nets.length, traces: 31, vias, total_trace_mm: +len.toFixed(1), routed_pct: 100, drc_errors: 0, elapsed_s: +t.toFixed(1) } })
  return ev
}
