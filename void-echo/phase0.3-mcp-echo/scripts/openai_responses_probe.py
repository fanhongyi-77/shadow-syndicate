#!/usr/bin/env python3
"""OpenAI-side verification probe for the VOID ECHO Phase 0.3 MCP server.

Runs the same three tools through the OpenAI Responses API so the server can be
validated against a second, independent MCP client stack.

Two connection modes (per OpenAI's MCP guide):

  --mode server-url   Remote MCP server. OpenAI only reaches servers on the
                      public internet, so a plain http://127.0.0.1 URL will NOT
                      work from their side. Pass a public https URL, or use tunnel mode.
  --mode tunnel       Secure MCP Tunnel. Pass --tunnel-id returned by the
                      tunnel-client; the local server stays private.

The API key is read from a file only (--key-file, default ~/.void-echo/openai.key).
It is never accepted from argv, never printed, never written to logs, and the
script refuses to run without it. Use --dry-run to inspect the exact request
without reading or sending any credential.

    # store the key once, hidden from screen and shell history:
    #   read -s "k?key: " && printf '%s' "$k" > ~/.void-echo/openai.key && unset k && chmod 600 ~/.void-echo/openai.key
    uv run python scripts/openai_responses_probe.py --dry-run
    uv run python scripts/openai_responses_probe.py --mode tunnel --tunnel-id tunnel_0123456789abcdef0123456789abcdef
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "gpt-5.2"
BASE_URL = "https://api.openai.com/v1"

CASES = [
    (
        "ping",
        "Call the void_echo_test `ping` tool once. Report the exact service name, "
        "version and status it returned, and nothing else.",
    ),
    (
        "echo",
        "Call the void_echo_test `echo` tool with text=\"VOID-ECHO-OPENAI\", count=3 "
        "and mode=\"wrap\". Report the first line and the last line of the payload, "
        "plus output_chars.",
    ),
    (
        "frame",
        "Call the void_echo_test `frame` tool with n=2. For each returned image, "
        "describe the background colour, the red shape and the blue shape, and state "
        "how many dark tick bars appear at the top-left of that image.",
    ),
]


def build_tools(args) -> list[dict]:
    tool: dict = {
        "type": "mcp",
        "server_label": args.label,
        "server_description": (
            "VOID ECHO Phase 0.3 test server: ping, echo, frame. Read-only, no side effects."
        ),
        "require_approval": "never",
    }
    if args.mode == "tunnel":
        tool["tunnel_id"] = args.tunnel_id
    else:
        tool["server_url"] = args.server_url
    if args.allowed_tools:
        tool["allowed_tools"] = args.allowed_tools.split(",")
    if args.defer_loading:
        tool["defer_loading"] = True
    return [tool]


def post(key: str, base: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{base}/responses",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def report(case: str, data: dict) -> None:
    print(f"\n--- case: {case}  status={data.get('status')}")
    for item in data.get("output", []):
        t = item.get("type")
        if t == "mcp_list_tools":
            tools = item.get("tools") or []
            err = item.get("error")
            print(f"    mcp_list_tools: {len(tools)} tool(s) {[x.get('name') for x in tools]}")
            if err:
                print(f"      ERROR: {err}")
        elif t == "mcp_call":
            out = item.get("output") or ""
            print(
                f"    mcp_call: name={item.get('name')} args={_clip(item.get('arguments'))}"
            )
            print(f"      error={item.get('error')}")
            print(f"      output: {_clip(out, 400)}")
            _scan_image_markers(out)
        elif t == "mcp_approval_request":
            print(f"    mcp_approval_request: {item.get('name')} id={item.get('id')}")
        elif t == "function_call":
            print(f"    function_call: {item.get('name')}")
        elif t == "reasoning":
            print("    reasoning: (present)")
        elif t == "message":
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "text"):
                    print(f"    model says: {_clip(part.get('text'), 600)}")
        else:
            print(f"    {t}")
    usage = data.get("usage") or {}
    if usage:
        print(f"    usage: in={usage.get('input_tokens')} out={usage.get('output_tokens')}")


def _scan_image_markers(output: str) -> None:
    """Record what actually happened to image content on the OpenAI path."""
    markers = {
        '"type":"image"': "image content block",
        '"type": "image"': "image content block",
        "image/png": "image/png mime",
        "data:image": "data URL",
        "base64": "base64 payload",
    }
    found = [label for needle, label in markers.items() if needle in output.replace(" ", "") or needle in output]
    if found:
        print(f"      image markers in tool output: {sorted(set(found))}")
    else:
        print("      image markers in tool output: NONE (image did not survive as image content)")


def _clip(value, limit: int = 200) -> str:
    if value is None:
        return "null"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"…(+{len(text) - limit})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["server-url", "tunnel"], default="tunnel")
    # tunnel_id format per official onboarding docs: tunnel_<32 lowercase alnum>
    # or tunnel_<4-char namespace>_<32 lowercase alnum>. Preserve the full returned id.
    ap.add_argument("--server-url", default="")
    ap.add_argument("--tunnel-id", default="")
    ap.add_argument("--label", default="void_echo_test")
    ap.add_argument("--model", default=os.environ.get("VOID_ECHO_OPENAI_MODEL", DEFAULT_MODEL))
    ap.add_argument("--allowed-tools", default="")
    ap.add_argument("--defer-loading", action="store_true")
    ap.add_argument("--case", default="all", choices=["all", "ping", "echo", "frame"])
    ap.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", BASE_URL))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--dry-run", action="store_true", help="print the request body and exit")
    ap.add_argument("--key-file", default=str(Path.home() / ".void-echo/openai.key"),
                    help="file holding the API key; the ONLY source. Never printed.")
    args = ap.parse_args()

    if args.mode == "server-url" and not args.server_url:
        ap.error("--mode server-url requires --server-url")
    if args.mode == "tunnel" and not args.tunnel_id:
        ap.error("--mode tunnel requires --tunnel-id")

    tools = build_tools(args)
    cases = [c for c in CASES if args.case == "all" or c[0] == args.case]

    if args.dry_run:
        print("POST {}/responses".format(args.base_url))
        for name, prompt in cases:
            body = {"model": args.model, "input": prompt, "tools": tools}
            print(f"\n--- {name}\n{json.dumps(body, indent=2, ensure_ascii=False)}")
        print("\n(dry-run: no request sent, no credential read)")
        return 0

    # File-only by design: the key must never arrive via chat, argv, or shell history.
    kf = Path(args.key_file).expanduser()
    if not kf.is_file():
        hint = '  read -s "k?key: " && printf "%s" "$k" > ' + str(kf) + " && unset k && chmod 600 " + str(kf)
        print(
            "key file not found: " + str(kf) + "\n"
            "Store it once with (nothing is echoed, nothing enters history):\n" + hint,
            file=sys.stderr,
        )
        return 2
    key = kf.read_text().strip()
    if not key:
        print(
            "key file is empty: " + str(kf) + "\n"
            "Nothing was requested. Re-store the key with the hidden prompt above.",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for name, prompt in cases:
        body = {"model": args.model, "input": prompt, "tools": tools}
        try:
            data = post(key, args.base_url, body, args.timeout)
        except urllib.error.HTTPError as exc:
            print(f"\n--- case: {name}  HTTP {exc.code}")
            print(f"    {_clip(exc.read().decode(), 500)}")
            failures += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"\n--- case: {name}  ERROR {type(exc).__name__}: {exc}")
            failures += 1
            continue
        report(name, data)
        if data.get("status") not in ("completed",):
            failures += 1

    print(f"\n== {len(cases) - failures}/{len(cases)} case(s) completed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
