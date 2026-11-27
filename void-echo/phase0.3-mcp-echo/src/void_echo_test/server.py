"""VOID ECHO Phase 0.3 — MCP Echo Server.

One Streamable HTTP MCP server, verified independently by DSH Desktop and by
OpenAI clients. Listens on localhost only. No Docker, no auth, no writes.

Tools
-----
ping()                    -> service identity + runtime state
echo(text, count, mode)   -> structured result, safe for very long text
frame(n)                  -> n real PNG images as MCP `type: image` blocks

Run
---
    uv run void-echo-mcp
    # or: .venv/bin/python -m void_echo_test.server

Endpoint: http://127.0.0.1:8765/mcp
"""

from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent
from pydantic import Field

from void_echo_test.png import ACCENTS, HEIGHT, SLASHES, WIDTH, render_frame

SERVER_NAME = "void_echo_test"
VERSION = "0.3.0"
STARTED_AT = time.time()

MAX_TEXT_CHARS = 200_000
MAX_COUNT = 500
MAX_FRAMES = 8

server = MCPServer(
    name=SERVER_NAME,
    version=VERSION,
    instructions=(
        "VOID ECHO Phase 0.3 echo server. Use ping for liveness, echo to verify "
        "multi-argument passing and long-text transport, and frame to verify that "
        "real PNG image content reaches the client and is visible to the model."
    ),
)


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@server.tool(
    title="Ping",
    description=(
        "Liveness and identity probe. Takes no arguments and returns the server "
        "name, version, uptime, listening endpoint and the limits that echo/frame enforce."
    ),
)
def ping() -> dict[str, Any]:
    """Return service name, version and runtime status."""
    now = time.time()
    return {
        "service": SERVER_NAME,
        "version": VERSION,
        "status": "ok",
        "uptime_seconds": round(now - STARTED_AT, 3),
        "epoch": round(now, 3),
        "endpoint": f"http://{_env('VOID_ECHO_HOST', '127.0.0.1')}:{_env('VOID_ECHO_PORT', '8765')}{_env('VOID_ECHO_PATH', '/mcp')}",
        "transport": "streamable-http",
        "limits": {
            "max_text_chars": MAX_TEXT_CHARS,
            "max_count": MAX_COUNT,
            "max_frames": MAX_FRAMES,
            "frame_size": f"{WIDTH}x{HEIGHT}",
        },
    }


@server.tool(
    title="Echo",
    description=(
        "Echo `text` `count` times using `mode`. Modes: 'repeat' joins the copies "
        "with newlines; 'wrap' tags each copy with its index; 'json' returns only the "
        "structured result without expanding the payload. Use a long `text` with a "
        "large `count` to verify long-result handling on the client side."
    ),
)
def echo(
    text: Annotated[str, Field(description="Payload to echo. Up to 200000 characters.")],
    count: Annotated[int, Field(ge=1, le=MAX_COUNT, description="How many copies to produce.")] = 1,
    mode: Annotated[
        Literal["repeat", "wrap", "json"],
        Field(description="Output shaping mode."),
    ] = "repeat",
) -> dict[str, Any]:
    """Return a complete structured result for an echoed payload."""
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text exceeds {MAX_TEXT_CHARS} characters")

    if mode == "repeat":
        payload = "\n".join([text] * count)
    elif mode == "wrap":
        payload = "\n".join(f"[{i + 1:04d}] {text}" for i in range(count))
    else:  # json
        payload = ""

    return {
        "mode": mode,
        "count": count,
        "text_sha256": _sha256(text),
        "input_chars": len(text),
        "output_chars": len(payload),
        "total_if_expanded": len(text) * count,
        "first_line": text.splitlines()[0][:120] if text else "",
        "payload": payload,
    }


@server.tool(
    title="Frame",
    structured_output=False,
    description=(
        "Generate `n` real PNG frames (360x240) with a light background, one red "
        "ellipse and one blue rectangle, plus `index+1` dark tick bars at top-left. "
        "When `secret` is -1 the server draws THREE pixel-only signals: 1-3 thick "
        "bars at top-right in one of 6 widely separated accent colours (teal, orange, "
        "purple, magenta, yellow, gray), plus a slash (backslash, slash or horizontal) "
        "with a filled DOT at its start point, inside the panel at bottom-centre. None of the three "
        "appears in any text block, so reporting all three correctly proves the image "
        "was actually seen (pure-guess chance 1/54). Each image is returned "
        "as a standard MCP `type: image` content block with canonical RFC 4648 "
        "base64, interleaved with a text block naming the frame."
    ),
)
def frame(
    n: Annotated[int, Field(ge=1, le=MAX_FRAMES, description="Number of frames to return.")] = 1,
    run: Annotated[
        str,
        Field(description="Optional caller-supplied run id, echoed into the grading log for correlation."),
    ] = "",
    as_text: Annotated[
        bool,
        Field(description=(
            "v4 experiment: when true, return the PNG ONLY as a base64 string inside a "
            "text block (no image content block at all). Clients that can execute code can "
            "decode it and forward it into their own visual input. When false, return the "
            "standard MCP image content block."
        )),
    ] = False,
    secret: Annotated[
        int,
        Field(
            ge=-1,
            le=9,
            description=(
                "Thick bars at top-right. 0 = none, 1-3 = that many bars. "
                "-1 = the SERVER picks a fresh random TRIPLE: bar count (1-3), accent "
                "colour (teal/orange/purple/magenta/yellow/gray) and slash direction "
                "(backslash/slash/horizontal), and writes all three only to its own local "
                "log. None of them appears in any text block, so guessing all three has "
                "probability 1/54."
            ),
        ),
    ] = 0,
) -> list[TextContent | ImageContent]:
    """Return `n` PNG images as standard MCP image content blocks.

    Returned as explicit content blocks (not a JSON-serialisable value) so the
    SDK cannot collapse them into a single structured text result.
    """
    if not run:
        run = uuid.uuid4().hex[:8]
    accent = "teal"
    slash = "backslash"
    if secret == -1:
        secret, accent, slash = _pick_secret(run)
    if as_text:
        # v4: image travels INSIDE a text block. No image content block is emitted,
        # so any correct report can only come from the text path.
        png = render_frame(0, secret, accent, slash)
        b64 = base64.b64encode(png).decode("ascii")
        return [
            TextContent(
                type="text",
                text=(
                    f"VOID_ECHO_B64_V1 run={run} sha256={_sha256(png)} bytes={len(png)} "
                    f"size={WIDTH}x{HEIGHT} mime=image/png\n"
                    "This is the whole image as canonical base64 inside a TEXT block; there is "
                    "no image content block in this result. Decode the data URL below, then "
                    "forward the decoded PNG into your visual input to look at it. "
                    "Report the run id, and the three pixel-only signals (bar count, accent "
                    "colour, slash direction). If you cannot obtain a viewable image, say so "
                    "instead of guessing."
                ),
            ),
            TextContent(type="text", text=f"data:image/png;base64,{b64}"),
        ]

    out: list[TextContent | ImageContent] = [
        TextContent(
            type="text",
            text=(
                f"VOID ECHO frame generator: run={run} | {n} frame(s), {WIDTH}x{HEIGHT} px, "
                "image/png, canonical base64. The bar count, accent colour and slash direction "
                "are deliberately absent from this text. Quote the run id back when reporting "
                "what you saw."
            ),
        )
    ]
    for i in range(n):
        png = render_frame(i, secret, accent, slash)
        out.append(
            TextContent(
                type="text",
                text=f"frame {i + 1}/{n}: light background, red ellipse, blue rectangle, {i + 1} dark bar(s) at top-left.",
            )
        )
        out.append(
            ImageContent(
                type="image",
                data=base64.b64encode(png).decode("ascii"),
                mime_type="image/png",
            )
        )
    return out


def _sha256(value: str | bytes) -> str:
    """SHA-256 of text (utf-8) or raw bytes."""
    import hashlib

    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    return hashlib.sha256(data).hexdigest()


def _pick_secret(run: str) -> tuple[int, str, str]:
    """Choose a random count, colour and slash; record all three LOCALLY.

    These are the grading ground truth. They are appended to out/secrets.log on
    this machine only and never enter a tool response, so a client that cannot
    see the pixels has a 1/54 chance of guessing the whole triple.
    """
    import random
    import time
    from pathlib import Path

    count = random.randint(1, 3)
    colour = random.choice(list(ACCENTS))
    direction = random.choice(list(SLASHES))
    try:
        Path("out").mkdir(exist_ok=True)
        with Path("out/secrets.log").open("a", encoding="utf-8") as fh:
            fh.write(
                f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\trun={run}\t"
                f"secret={count}\tcolour={colour}\tslash={direction}\n"
            )
    except OSError:
        pass  # grading log is best-effort; never fail a call over it
    return count, colour, direction


def build_app():
    """Return the ASGI app (used by tests that mount the server in-process)."""
    return server.streamable_http_app(
        streamable_http_path=_env("VOID_ECHO_PATH", "/mcp"),
        json_response=_env("VOID_ECHO_JSON_RESPONSE", "0") == "1",
    )


def main() -> None:
    host = _env("VOID_ECHO_HOST", "127.0.0.1")
    port = int(_env("VOID_ECHO_PORT", "8765"))
    path = _env("VOID_ECHO_PATH", "/mcp")
    json_response = _env("VOID_ECHO_JSON_RESPONSE", "0") == "1"

    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "streamable_http_path": path,
        "json_response": json_response,
    }

    # DNS-rebinding protection is on by default and pins the allowed Host header
    # to localhost. OpenAI's Secure MCP Tunnel presents a different Host, so
    # opt out explicitly when tunneling. Never expose this host to the network.
    if _env("VOID_ECHO_ALLOW_ANY_HOST", "0") == "1":
        try:
            from mcp.server.transport_security import TransportSecuritySettings

            kwargs["transport_security"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            )
        except Exception as exc:  # pragma: no cover - SDK layout guard
            print(f"[void-echo] transport_security unavailable: {exc}")

    print(f"[void-echo] {SERVER_NAME} v{VERSION} -> http://{host}:{port}{path}")
    print(f"[void-echo] json_response={json_response} allow_any_host={_env('VOID_ECHO_ALLOW_ANY_HOST', '0') == '1'}")
    server.run(transport="streamable-http", **kwargs)


if __name__ == "__main__":
    main()
