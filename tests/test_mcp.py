"""Smoke test: spawn the MCP server and speak JSON-RPC over stdio."""
from pathlib import Path
import json
import subprocess
import sys
import threading
import time

SERVER = str(Path(__file__).resolve().parents[1] / "server.py")


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-u", SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )

    lines: list[str] = []
    errors: list[str] = []

    def reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))

    def err_reader():
        assert proc.stderr is not None
        for line in proc.stderr:
            errors.append(line.rstrip("\n"))

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=err_reader, daemon=True).start()

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]

    assert proc.stdin is not None
    for message in messages:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        time.sleep(0.3)

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and len(lines) < 2 and proc.poll() is None:
        time.sleep(0.1)

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()

    init_ok = False
    tools: list[str] = []
    print("--- stdout ---")
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            print("NON-JSON:", line[:200])
            continue
        if payload.get("id") == 1:
            info = payload.get("result", {}).get("serverInfo", {})
            print("initialize:", info, "protocol", payload.get("result", {}).get("protocolVersion"))
            init_ok = "serverInfo" in payload.get("result", {})
        elif payload.get("id") == 2:
            tools = [t["name"] for t in payload.get("result", {}).get("tools", [])]
            print(f"tools ({len(tools)}):", tools)
        else:
            print(json.dumps(payload)[:300])

    print("--- stderr ---")
    for line in errors[-10:]:
        print(line)

    assert init_ok, "MCP server failed to respond to initialize"
    assert len(tools) == 8, f"Expected 8 MCP tools, got {len(tools)}: {tools}"
    print("mcp smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
