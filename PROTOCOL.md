# ETCH — Frontend ⇄ Backend Protocol

ETCH turns a natural-language device description into a manufacturable 2-layer PCB.
Backend: Python/FastAPI on `http://localhost:8000`. Frontend: Vite/React/Three.js on `http://localhost:5173`
(Vite proxies `/api` and `/ws` to the backend).

## Transport

WebSocket `ws://localhost:8000/ws/design`. One design run per socket connection.

Client → server:
```json
{"type":"start","prompt":"USB-C powered ESP32 sensor node ...","options":{"color":"black","demo":false}}
{"type":"cancel"}
```
`options.color` ∈ `green | black | purple | blue | red | white` (solder mask). `options.demo=true` forces cached agent output (no LLM call).

Server → client: a stream of JSON events, every event has `"type"`, `"seq"` (int, increasing) and `"t"` (seconds since run start, float).

## Units & coordinates

All geometry in **millimetres**, board space: origin at board bottom-left corner, **x right, y up**. Rotation in degrees CCW.
Layers: `"F.Cu"` (top copper, components side), `"B.Cu"` (bottom copper). Every component is on the top side.

## Pipeline stages (in order)

`brief → architect → components → netlist → schematic → placement → routing → drc → thermal → power → export`

```json
{"type":"status","stage":"routing","state":"start|done|error","message":"Routing 47 nets"}
```

## Events

### thought — agent narration (streamed text deltas, append to a running transcript)
```json
{"type":"thought","text":"The board needs a 3.3 V rail; the ESP32 draws up to 500 mA during Wi-Fi TX so an AMS1117 is marginal..."}
```

### design — high-level plan (emitted once after architect stage)
```json
{"type":"design","design":{
  "name":"AirNode","tagline":"USB-C powered ESP32 environmental sensor",
  "summary":"2–3 sentences",
  "board":{"width":58.0,"height":42.0,"corner_radius":2.0,"mounting_holes":true,"color":"black","layers":2},
  "power":{"input":"USB-C 5 V","rails":["3V3"]},
  "estimated_cost_usd":6.4
}}
```

### component — one per part, in order the agent picks them
```json
{"type":"component","component":{
  "ref":"U1","part_id":"esp32-wroom-32e","name":"ESP32-WROOM-32E","value":"",
  "category":"mcu",
  "description":"Wi-Fi + BLE module, 4 MB flash",
  "footprint":"ESP32-WROOM-32E","package":"Module 18×25.5 mm",
  "lcsc":"C701341","price_usd":2.9,
  "purpose":"Main controller; Wi-Fi for cloud upload.",
  "pins":[{"num":"1","name":"GND","type":"gnd"},{"num":"2","name":"3V3","type":"power_in"},{"num":"3","name":"EN","type":"input"}],
  "body":{"w":18.0,"h":25.5,"z":3.1,"style":"module"},
  "power_w":0.8
}}
```
`category` ∈ `mcu | power | passive | connector | sensor | led | switch | ic | crystal | module | mechanical | protection`
`pins[].type` ∈ `power_in | power_out | gnd | input | output | bidirectional | passive | nc`
`body.style` ∈ `module | chip | sot | passive | connector | usb | header | led | switch | crystal | hole | electrolytic | tht`

### netlist — after all components
```json
{"type":"netlist","nets":[
  {"name":"GND","cls":"gnd","pins":["U1.1","C1.2","J1.A1"]},
  {"name":"3V3","cls":"power","pins":["U1.2","C1.1","U2.2"],"voltage":3.3,"current_ma":600},
  {"name":"SDA","cls":"signal","pins":["U1.14","U3.4","R1.2"]}
]}
```
`cls` ∈ `gnd | power | signal | highspeed | analog`

### board — geometry container for the 3D view (emitted before placement)
```json
{"type":"board","board":{
  "width":58.0,"height":42.0,"corner_radius":2.0,"color":"black",
  "outline":[[0,0],[58,0],[58,42],[0,42]],
  "holes":[{"x":3.5,"y":3.5,"drill":3.2,"diameter":6.0}],
  "footprints":{
    "U1":{
      "pads":[{"num":"1","shape":"rect","x":-9.0,"y":8.9,"w":1.5,"h":0.9,"layer":"F.Cu"}],
      "courtyard":{"x":-9.5,"y":-13.5,"w":19.0,"h":27.0},
      "body":{"x":-9.0,"y":-12.75,"w":18.0,"h":25.5,"z":3.1,"style":"module"},
      "silk":[[-9,-12.75,9,-12.75],[9,-12.75,9,12.75]]
    }
  },
  "texts":[{"text":"AIRNODE v1","x":29,"y":40,"size":1.2,"layer":"F.SilkS","rot":0}]
}}
```
Pad `shape` ∈ `rect | roundrect | circle | oval`. Pad `layer` ∈ `F.Cu | through` (`through` pads have `drill`).
Pad coordinates are relative to the footprint origin, unrotated. Footprint placement rotates pads by `rot` and translates by `(x,y)`.

### placement — animation frames (≈60 during annealing)
```json
{"type":"placement","iteration":1200,"total":8000,"temperature":12.5,"cost":812.3,
 "positions":{"U1":[29.0,21.0,0],"C1":[12.0,10.0,90]}}
{"type":"placement_final","positions":{"U1":[29.0,21.0,0]}}
{"type":"ratsnest","lines":[[x1,y1,x2,y2,"NET"],...]}
```

### routing — streamed one route at a time (this is the main animation)
```json
{"type":"route_begin","net":"SDA","cls":"signal"}
{"type":"trace","net":"SDA","layer":"F.Cu","width":0.25,"points":[[10.0,5.0],[10.0,9.0],[14.0,13.0]]}
{"type":"via","net":"SDA","x":14.0,"y":13.0,"drill":0.3,"diameter":0.6}
{"type":"route_fail","net":"SDA","reason":"no path"}
{"type":"ripup","net":"SDA","traces":2,"vias":1}
{"type":"reset_routing","reason":"refining fine-pitch escapes to 0.1 mm"}
{"type":"routing_progress","routed":12,"total":47,"length_mm":312.4,"vias":9}
{"type":"pour","layer":"B.Cu","net":"GND","clearance":0.3}
```
A net may produce several `trace` events (one per polyline segment run per layer). The bottom layer is a GND pour: render B.Cu as solid copper with a `clearance`-wide gap around non-GND B.Cu traces, vias and through-pads.

`ripup` removes a net's previous copper. `reset_routing` clears all routing geometry, failures and pour state before
a refinement attempt or restoration of the better result; subsequent events rebuild it. The final `routing_progress`
counts successfully routed nets, excluding unresolved nets and an isolated GND plane. A completed routing stage does
not imply that every net succeeded; use DRC and the independent KiCad check for completion/validation.

### drc
```json
{"type":"drc","passed":true,"rules":{"min_trace_mm":0.127,"min_clearance_mm":0.127,"min_drill_mm":0.3,"min_annular_mm":0.13,"fab":"JLCPCB 2-layer"},
 "violations":[{"code":"clearance","severity":"error","message":"Trace SDA to pad R3.1: 0.11 mm < 0.127 mm","x":12.1,"y":9.3,"layer":"F.Cu"}],
 "checks":[{"name":"Clearance","count":312,"ok":true},{"name":"Trace width","count":47,"ok":true},{"name":"Connectivity","count":47,"ok":true}]}
```

### thermal — animation frames of a steady-state heat solve
```json
{"type":"thermal","frame":3,"total":24,"cols":58,"rows":42,"grid":[...rows*cols floats °C, row 0 = y=0...],"min_c":25.0,"max_c":48.2,
 "hotspots":[{"ref":"U2","c":48.2}]}
```

### power — DC analysis of power rails
```json
{"type":"power","rails":[{"net":"3V3","voltage":3.3,"current_ma":600,"length_mm":38.2,"width_mm":0.5,"resistance_mohm":22.4,"drop_mv":13.4,"ok":true}]}
```

### spice — optional, if ngspice is available (a transient sim of the power input stage)
```json
{"type":"spice","title":"3V3 rail load step","x_label":"t (ms)","y_label":"V","series":[{"name":"V(3V3)","x":[...],"y":[...]}]}
```

### artifacts — export done
```json
{"type":"artifacts","run_id":"a1b2c3","zip_url":"/api/runs/a1b2c3/etch-airnode-gerbers.zip",
 "files":[{"name":"AirNode-F_Cu.gtl","kind":"gerber","size":18233},{"name":"AirNode.kicad_pcb","kind":"kicad","size":50123},{"name":"bom.csv","kind":"bom","size":900}],
 "kicad":{"available":true,"drc_passed":true,"violations":0,"unconnected":0}}
```

### done / error
```json
{"type":"done","stats":{"components":24,"nets":31,"traces":112,"vias":18,"total_trace_mm":642.1,"routed_pct":100,"drc_errors":0,"elapsed_s":48.2}}
{"type":"error","message":"..."}
```

## HTTP

- `GET /api/health` → `{"ok":true,"llm":"claude-cli|anthropic|cache","kicad":true,"ngspice":false}`
- `GET /api/examples` → `[{"title":"...","prompt":"..."}]` (suggested prompts; the ones with cached agent output are marked `"cached":true`)
- `GET /api/runs/{run_id}/{filename}` → download an artifact (zip or individual file)
- `GET /api/runs/{run_id}/events.json` → full event log of a run (used for replay)
