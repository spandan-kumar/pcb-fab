"""LLM backends: Claude Code CLI (`claude -p`, uses the user's subscription), Anthropic SDK, or cached demo output.

Everything streams text deltas through an async callback so the UI can show the agent thinking live.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from typing import AsyncIterator, Callable, Awaitable

CACHE_DIR = os.path.join(os.path.dirname(__file__), "demo_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def backend_name() -> str:
    if os.environ.get("ETCH_LLM") == "cache":
        return "cache"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if shutil.which("claude"):
        return "claude-cli"
    return "cache"


def _cache_key(system: str, prompt: str) -> str:
    # keyed on the user prompt only, so system-prompt tweaks don't invalidate the demo cache
    return hashlib.sha256((os.environ.get("ETCH_PROMPT_VERSION", "1") + "\n---\n" + prompt).encode()).hexdigest()[:24]


def cache_path(system: str, prompt: str) -> str:
    return os.path.join(CACHE_DIR, _cache_key(system, prompt) + ".txt")


def has_cached(system: str, prompt: str) -> bool:
    return os.path.exists(cache_path(system, prompt))


async def stream_completion(system: str, prompt: str, on_delta: Callable[[str], Awaitable[None]],
                            prefer_cache: bool = False, model: str | None = None) -> str:
    """Stream a completion; returns the full text. Caches every successful result for demo replay."""
    cp = cache_path(system, prompt)
    if (prefer_cache or backend_name() == "cache") and os.path.exists(cp):
        text = open(cp).read()
        # replay with a typewriter cadence
        chunk = 24
        for i in range(0, len(text), chunk):
            await on_delta(text[i:i + chunk])
            await asyncio.sleep(0.012)
        return text
    be = backend_name()
    if be == "anthropic":
        text = await _anthropic_stream(system, prompt, on_delta, model)
    elif be == "claude-cli":
        try:
            text = await _claude_cli_stream(system, prompt, on_delta, model)
        except RuntimeError as e:
            if "safeguards" in str(e) or "flagged" in str(e):
                await on_delta("\n_(primary model declined — retrying with claude-sonnet-5)_\n")
                text = await _claude_cli_stream(system, prompt, on_delta, "claude-sonnet-5")
            else:
                raise
    else:
        raise RuntimeError("No LLM backend available (install Claude Code CLI or set ANTHROPIC_API_KEY) and no cached output for this prompt.")
    if text.strip():
        with open(cp, "w") as f:
            f.write(text)
    return text


async def _claude_cli_stream(system: str, prompt: str, on_delta, model: str | None) -> str:
    cwd = tempfile.mkdtemp(prefix="etch_llm_")
    args = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--tools", "", "--no-session-persistence", "--system-prompt", system, "--setting-sources", ""]
    mdl = model or os.environ.get("ETCH_CLAUDE_MODEL", "claude-fable-5-1")
    if mdl:
        args += ["--model", mdl]
    eff = os.environ.get("ETCH_CLAUDE_EFFORT")
    if eff:
        args += ["--effort", eff]
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    proc = await asyncio.create_subprocess_exec(*args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    text_parts: list[str] = []
    final_result = None
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        try:
            ev = json.loads(line.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "stream_event":
            e = ev.get("event", {})
            if e.get("type") == "content_block_delta":
                d = e.get("delta", {})
                if d.get("type") == "text_delta":
                    text_parts.append(d["text"])
                    await on_delta(d["text"])
        elif t == "result":
            final_result = ev.get("result")
            if ev.get("is_error"):
                raise RuntimeError(f"claude CLI error: {str(final_result)[:300]}")
    await proc.wait()
    text = "".join(text_parts)
    if not text and final_result:
        text = final_result
        await on_delta(text)
    if proc.returncode not in (0, None) and not text:
        err = (await proc.stderr.read()).decode()[-500:] if proc.stderr else ""
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {err}")
    return text


async def _anthropic_stream(system: str, prompt: str, on_delta, model: str | None) -> str:
    from anthropic import AsyncAnthropic  # type: ignore

    client = AsyncAnthropic()
    parts = []
    async with client.messages.stream(
        model=model or "claude-opus-5",
        max_tokens=16000,
        system=system,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            parts.append(text)
            await on_delta(text)
    return "".join(parts)
