"""ETCH backend — FastAPI + WebSocket."""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import llm, pipeline
from .agent import SYSTEM, user_prompt
from .analysis import ngspice_available
from .kicad_export import kicad_cli

app = FastAPI(title="ETCH", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

EXAMPLES = [
    {"title": "ESP32 environmental node", "emoji": "🌡️",
     "prompt": "A USB-C powered ESP32 environmental sensor node with an SHT31 temperature/humidity sensor, a BME280 pressure sensor, "
               "a status RGB LED (WS2812B), boot/reset buttons, and a Qwiic connector for expansion. Push data over Wi-Fi."},
    {"title": "LiPo IoT beacon", "emoji": "🔋",
     "prompt": "A battery powered ESP32-C3 beacon: LiPo battery on JST-PH with TP4056 USB-C charging, a 3.3V LDO, a tactile button, "
               "one status LED, and an I2C accelerometer (MPU-6050) to wake on motion. Small board."},
    {"title": "Dual motor robot driver", "emoji": "🤖",
     "prompt": "A robot motor controller: ESP32-S3 with native USB-C, DRV8833 dual H-bridge for two DC motors on screw terminals, "
               "7-12V barrel jack input with a TPS54302 buck to 5V and an LDO to 3.3V, reverse-polarity protection, an ultrasonic sensor header, and two servo headers."},
    {"title": "Arduino-style AVR board", "emoji": "🔧",
     "prompt": "A compact Arduino-compatible board: ATmega328P with 16MHz crystal, CH340C USB-C serial, auto-reset, ICSP header, "
               "power and TX/RX LEDs, AMS1117 5V→3.3V (board runs at 5V from USB), and 1x10 + 1x8 pin headers for all IO."},
    {"title": "ESP32-S3 data logger", "emoji": "💾",
     "prompt": "An ESP32-S3 data logger with a microSD slot over SPI, a DS3231 RTC with CR2032 backup, an ADS1115 16-bit ADC on a screw terminal "
               "input, native USB-C for power and programming, boot/reset buttons, and a user LED. 3.3V system."},
    {"title": "RS-485 industrial node", "emoji": "🏭",
     "prompt": "An industrial RS-485 sensor node: ESP32-WROOM-32E, MAX485 transceiver on a 3-pin screw terminal, 12V input via barrel jack with "
               "MP1584 buck to 5V and AP2112K to 3.3V, a relay output (SRD-05VDC driven by AO3400 MOSFET with flyback diode) on a screw terminal, "
               "DS18B20 temperature probe header, and status LEDs."},
]


@app.get("/api/health")
async def health():
    return {"ok": True, "llm": llm.backend_name(), "kicad": bool(kicad_cli()), "ngspice": ngspice_available()}


@app.get("/api/examples")
async def examples():
    out = []
    for e in EXAMPLES:
        out.append({**e, "cached": llm.has_cached(SYSTEM, user_prompt(e["prompt"]))})
    return out


@app.get("/api/runs")
async def list_runs():
    runs = []
    for rid in sorted(os.listdir(pipeline.RUNS_DIR)):
        p = os.path.join(pipeline.RUNS_DIR, rid, "events.json")
        if os.path.exists(p):
            try:
                with open(p) as f:
                    evs = json.load(f)
                first = next((e for e in evs if e["type"] == "run"), {})
                dsg = next((e for e in evs if e["type"] == "design"), {}).get("design", {})
                done = next((e for e in evs if e["type"] == "done"), None)
                runs.append({"run_id": rid, "prompt": first.get("prompt", ""), "name": dsg.get("name"), "done": bool(done),
                             "stats": done["stats"] if done else None, "mtime": os.path.getmtime(p)})
            except Exception:
                pass
    runs.sort(key=lambda r: -r["mtime"])
    return runs


@app.get("/api/runs/{run_id}/{path:path}")
async def run_file(run_id: str, path: str):
    base = os.path.realpath(os.path.join(pipeline.RUNS_DIR, run_id))
    full = os.path.realpath(os.path.join(base, path))
    if not full.startswith(base) or not os.path.isfile(full):
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "application/json" if full.endswith(".json") else None
    return FileResponse(full, media_type=media, filename=os.path.basename(full) if full.endswith(".zip") else None)


@app.websocket("/ws/design")
async def ws_design(ws: WebSocket):
    await ws.accept()
    task: asyncio.Task | None = None

    async def send(ev: dict):
        try:
            await ws.send_text(json.dumps(ev))
        except Exception:
            pass

    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "start" and task is None:
                prompt = str(data.get("prompt", "")).strip() or EXAMPLES[0]["prompt"]
                task = asyncio.create_task(pipeline.design(prompt, data.get("options", {}) or {}, send))
            elif data.get("type") == "cancel" and task:
                task.cancel()
                await send({"type": "error", "message": "cancelled"})
    except WebSocketDisconnect:
        pass
    finally:
        if task and not task.done():
            task.cancel()


def main():
    import uvicorn
    uvicorn.run("etch.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), reload=False)


if __name__ == "__main__":
    main()
