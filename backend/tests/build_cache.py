"""Run the full pipeline (real LLM) for every example prompt; caches agent output + stores replayable runs."""
import asyncio, json, sys, time
from etch import pipeline
from etch.main import EXAMPLES

async def main():
    only = sys.argv[1:] 
    for i, ex in enumerate(EXAMPLES):
        if only and str(i) not in only:
            continue
        t0 = time.time()
        print(f"=== [{i}] {ex['title']}", flush=True)
        last = {}
        async def send(ev):
            if ev["type"] in ("status", "route_fail", "error", "done"):
                print(f"  {ev['t']:6.1f}s {json.dumps({k: v for k, v in ev.items() if k not in ('seq','t')})[:300]}", flush=True)
            if ev["type"] == "drc":
                print(f"  DRC passed={ev['passed']} errors={ev['errors']} warnings={ev['warnings']}", flush=True)
            if ev["type"] == "artifacts":
                print(f"  KiCad: {json.dumps(ev['kicad'])[:300]}", flush=True)
        run = await pipeline.design(ex["prompt"], {"color": "black", "demo": True}, send)
        print(f"  run {run.id} done in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
