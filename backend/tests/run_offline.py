"""Run the full pipeline with a canned agent answer (no LLM). Usage: uv run python -m tests.run_offline"""
import asyncio
import json
import sys
import time

from etch import llm, pipeline

CANNED = """## Reasoning
This is a canned test design: a USB-C powered ESP32 sensor node with an SHT31 sensor, 3.3 V LDO, CH340C programming path, boot/reset buttons and a status LED.

```json
{
 "name": "TestNode", "tagline": "ESP32 sensor node (offline test)", "summary": "Test board.",
 "board": {"width": 58, "height": 42, "mounting_holes": true},
 "power": {"input": "USB-C 5V", "rails": [{"net":"VBUS","voltage":5.0,"current_ma":600},{"net":"3V3","voltage":3.3,"current_ma":500}]},
 "components": [
  {"ref":"U1","part":"esp32-wroom-32e","value":"","purpose":"Main MCU with Wi-Fi"},
  {"ref":"U2","part":"ams1117-3.3","value":"3.3V","purpose":"5V to 3.3V LDO"},
  {"ref":"U3","part":"sht31","value":"","purpose":"Temperature/humidity"},
  {"ref":"U4","part":"ch340c","value":"","purpose":"USB-UART programming"},
  {"ref":"U5","part":"tvs-usblc6","value":"","purpose":"USB ESD protection"},
  {"ref":"J1","part":"usb-c-16p","value":"","purpose":"Power + programming"},
  {"ref":"J2","part":"qwiic","value":"","purpose":"I2C expansion"},
  {"ref":"C1","part":"c-0805","value":"10uF","purpose":"LDO input"},
  {"ref":"C2","part":"c-0805","value":"10uF","purpose":"LDO output"},
  {"ref":"C3","part":"c-0603","value":"100nF","purpose":"ESP32 decoupling"},
  {"ref":"C4","part":"c-0603","value":"100nF","purpose":"EN RC"},
  {"ref":"C5","part":"c-0603","value":"100nF","purpose":"SHT31 decoupling"},
  {"ref":"C6","part":"c-0603","value":"100nF","purpose":"CH340 V3"},
  {"ref":"C7","part":"c-0603","value":"100nF","purpose":"CH340 VCC"},
  {"ref":"R1","part":"r-0603","value":"10k","purpose":"EN pull-up"},
  {"ref":"R2","part":"r-0603","value":"5.1k","purpose":"CC1 pull-down"},
  {"ref":"R3","part":"r-0603","value":"5.1k","purpose":"CC2 pull-down"},
  {"ref":"R4","part":"r-0603","value":"4.7k","purpose":"SDA pull-up"},
  {"ref":"R5","part":"r-0603","value":"4.7k","purpose":"SCL pull-up"},
  {"ref":"R6","part":"r-0603","value":"1k","purpose":"LED series"},
  {"ref":"R7","part":"r-0603","value":"1k","purpose":"Power LED series"},
  {"ref":"D1","part":"led-0603","value":"green","purpose":"Status LED"},
  {"ref":"D2","part":"led-0603","value":"red","purpose":"Power LED"},
  {"ref":"SW1","part":"sw-tact-smd","value":"BOOT","purpose":"Boot button"},
  {"ref":"SW2","part":"sw-tact-smd","value":"RESET","purpose":"Reset button"}
 ],
 "nets": [
  {"name":"GND","cls":"gnd","pins":["U1.1","U1.15","U1.38","U1.39","U2.1","U3.8","U3.2","U4.1","U5.2","J1.A1B12","J1.B1A12","J1.S1","J1.S2","J1.S3","J1.S4","J2.1","C1.2","C2.2","C3.2","C4.2","C5.2","C6.2","C7.2","R2.2","R3.2","D1.1","D2.1","SW1.3","SW2.3"]},
  {"name":"VBUS","cls":"power","pins":["J1.A4B9","J1.B4A9","U2.3","C1.1","U4.16","C7.1","U5.5"]},
  {"name":"3V3","cls":"power","pins":["U2.2","U2.4","U1.2","C2.1","C3.1","U3.5","U3.6","C5.1","R1.1","R4.1","R5.1","J2.2","R7.1"]},
  {"name":"CC1","pins":["J1.A5","R2.1"]},
  {"name":"CC2","pins":["J1.B5","R3.1"]},
  {"name":"USB_DP","cls":"highspeed","pins":["J1.A6","J1.B6","U5.1","U5.6","U4.5"]},
  {"name":"USB_DM","cls":"highspeed","pins":["J1.A7","J1.B7","U5.3","U5.4","U4.6"]},
  {"name":"V3","pins":["U4.4","C6.1"]},
  {"name":"EN","pins":["U1.3","R1.2","C4.1","SW2.1"]},
  {"name":"IO0","pins":["U1.25","SW1.1"]},
  {"name":"SDA","pins":["U1.33","U3.1","R4.2","J2.3"]},
  {"name":"SCL","pins":["U1.36","U3.4","R5.2","J2.4"]},
  {"name":"LED","pins":["U1.24","R6.1"]},
  {"name":"LED_A","pins":["R6.2","D1.2"]},
  {"name":"PWR_LED","pins":["R7.2","D2.2"]},
  {"name":"TXD0","pins":["U1.35","U4.3"]},
  {"name":"RXD0","pins":["U1.34","U4.2"]}
 ],
 "notes": ["offline canned design"],
 "estimated_cost_usd": 7.1
}
```
"""


async def fake_stream(system, prompt, on_delta, prefer_cache=False, model=None):
    for i in range(0, len(CANNED), 200):
        await on_delta(CANNED[i:i + 200])
    return CANNED


async def main():
    llm.stream_completion = fake_stream  # type: ignore
    counts = {}
    t0 = time.time()

    async def send(ev):
        counts[ev["type"]] = counts.get(ev["type"], 0) + 1
        if ev["type"] in ("status", "route_fail", "error", "artifacts", "done", "pour", "power", "ripup"):
            print(f"{ev['t']:7.2f}s", json.dumps({k: v for k, v in ev.items() if k not in ('seq', 't', 'files')})[:400])
        if ev["type"] == "drc":
            print(f"{ev['t']:7.2f}s DRC passed={ev['passed']} errors={ev['errors']} warnings={ev['warnings']}")
            for v in ev["violations"][:8]:
                print("      ", v["severity"], v["code"], v["message"])
        if ev["type"] == "spice":
            print(f"{ev['t']:7.2f}s SPICE {ev['title']} min={ev['min_v']} undershoot={ev['undershoot_mv']}mV pts={len(ev['series'][0]['x'])}")

    run = await pipeline.design("offline test", {"color": "black"}, send)
    print("events:", counts)
    print("run dir:", run.dir, "elapsed %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    asyncio.run(main())
