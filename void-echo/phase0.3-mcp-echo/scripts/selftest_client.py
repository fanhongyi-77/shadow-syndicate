#!/usr/bin/env python3
"""Client-side verification harness for the VOID ECHO Phase 0.3 MCP server.

Runs the checks that do NOT depend on any AI product: transport handshake,
tool discovery, argument passing, long-result handling and real PNG image
content. Exits non-zero on the first FAIL.

    uv run python scripts/selftest_client.py [--url http://127.0.0.1:8765/mcp]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from mcp import ClientSession

try:  # SDK 2.x renamed the client and now yields 2 streams, not 3
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
except ImportError:  # SDK 1.x name
    from mcp.client.streamable_http import streamablehttp_client  # type: ignore

CANONICAL_B64 = re.compile(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
OUT = Path(__file__).resolve().parent.parent / "out"

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, "PASS" if ok else "FAIL", detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        raise AssertionError(f"{name}: {detail}")


async def run(url: str) -> int:
    OUT.mkdir(exist_ok=True)
    print(f"== connecting {url}")

    # SDK default caps a single SSE event at 1 MiB; long B-stype payloads need more.
    try:
        _cm = streamablehttp_client(url, max_sse_event_size=32 * 1024 * 1024)
    except TypeError:
        _cm = streamablehttp_client(url)
    async with _cm as _streams:
        # SDK 2.x yields (read, write); SDK 1.x yields (read, write, get_session_id).
        read, write = _streams[0], _streams[1]
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            info = init.server_info
            check(
                "1. streamable-http handshake",
                True,
                f"server={info.name} v{info.version} protocol={init.protocol_version}",
            )

            tools = (await s.list_tools()).tools
            names = sorted(t.name for t in tools)
            check(
                "2. tool discovery (3 tools)",
                names == ["echo", "frame", "ping"],
                f"found={names}",
            )
            schemas = {t.name: (t.input_schema or {}) for t in tools}
            props = sorted((schemas.get("echo") or {}).get("properties", {}).keys())
            check(
                "2b. echo input schema exposes 3 params",
                props == ["count", "mode", "text"],
                f"properties={props} required={(schemas.get('echo') or {}).get('required')}",
            )

            r = await s.call_tool("ping", {})
            payload = json.loads(_first_text(r))
            check(
                "3. ping returns identity",
                payload.get("service") == "void_echo_test" and payload.get("status") == "ok",
                f"service={payload.get('service')} v{payload.get('version')} uptime={payload.get('uptime_seconds')}s",
            )

            # --- multi-argument passing -------------------------------------
            long_text = "VOID-ECHO-PHASE0.3 " + "行中文测试 αβγ " * 400  # ~ 9k chars
            r = await s.call_tool(
                "echo", {"text": long_text, "count": 12, "mode": "wrap"}
            )
            out = json.loads(_first_text(r))
            check(
                "4. echo multi-arg (text/count/mode)",
                out["count"] == 12
                and out["mode"] == "wrap"
                and out["input_chars"] == len(long_text)
                and out["first_line"].startswith("VOID-ECHO-PHASE0.3"),
                f"count={out['count']} mode={out['mode']} in={out['input_chars']} out={out['output_chars']}",
            )
            check(
                "4b. echo payload ordering",
                out["payload"].splitlines()[0].startswith("[0001] ")
                and out["payload"].splitlines()[-1].startswith("[0012] "),
                f"lines={len(out['payload'].splitlines())}",
            )
            structured = getattr(r, "structured_content", None)
            check(
                "4c. structured_content present",
                isinstance(structured, dict) and "result" in structured or isinstance(structured, dict),
                f"keys={list(structured)[:4] if isinstance(structured, dict) else type(structured).__name__}",
            )

            # --- long result -------------------------------------------------
            try:
                r = await s.call_tool("echo", {"text": "L" * 60_000, "count": 30, "mode": "repeat"})
                blob = _first_text(r)
                check(
                    "5. long-text result 1.8MB (raised SSE cap)",
                    len(blob) > 1_500_000,
                    f"result_chars={len(blob):,} (~{len(blob) / 4 / 1000:.0f}k est. tokens)",
                )
            except Exception as exc:  # noqa: BLE001
                check("5. long-text result", False, f"{type(exc).__name__}: {exc}")

            # --- error surface ----------------------------------------------
            try:
                r = await s.call_tool("echo", {"text": "x", "count": 0, "mode": "repeat"})
                check("6. invalid arg surfaces as isError", bool(r.is_error), f"isError={r.is_error}")
            except Exception as exc:  # noqa: BLE001
                check("6. invalid arg surfaces as error", True, f"raised {type(exc).__name__}")

            # --- images ------------------------------------------------------
            r = await s.call_tool("frame", {"n": 3})
            blocks = r.content
            kinds = [getattr(b, "type", "?") for b in blocks]
            images = [b for b in blocks if getattr(b, "type", "") == "image"]
            texts = [b for b in blocks if getattr(b, "type", "") == "text"]
            check(
                "7. frame returns MCP image content blocks",
                len(images) == 3 and any(t.text.startswith("VOID ECHO frame generator") for t in texts),
                f"block_kinds={kinds}",
            )

            ok_b64 = ok_magic = ok_dims = True
            digests = []
            for i, im in enumerate(images):
                data = im.data
                ok_b64 &= bool(CANONICAL_B64.match(data))
                raw = base64.b64decode(data)
                ok_magic &= raw.startswith(PNG_MAGIC)
                w, h = struct.unpack(">II", raw[16:24])
                ok_dims &= (w, h) == (360, 240)
                digests.append(hashlib.sha256(raw).hexdigest()[:12])
                (OUT / f"frame_{i + 1}.png").write_bytes(raw)
            check("7b. base64 is canonical RFC 4648", ok_b64, f"mime={images[0].mime_type}")
            check("7c. bytes decode as real PNG", ok_magic, f"sha256[:12]={digests}")
            check("7d. dimensions 360x240", ok_dims, "saved -> out/frame_1..3.png")
            check(
                "7e. frames are distinct",
                len(set(digests)) == len(digests),
                f"unique={len(set(digests))}/{len(digests)}",
            )

    print("\n== summary")
    for name, status, detail in results:
        print(f"  {status:4}  {name:44} {detail[:70]}")
    print(f"\nALL {len(results)} CHECKS PASSED — images at {OUT}")
    return 0


def _first_text(result) -> str:
    for block in result.content:
        if getattr(block, "type", "") == "text":
            return block.text
    raise AssertionError("no text block in result")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    args = ap.parse_args()
    try:
        return asyncio.run(run(args.url))
    except AssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
