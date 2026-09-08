#!/usr/bin/env python3
"""Read-only RPC checks: no game keys, frame advances, or focus changes."""
import json
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time

BINARY = Path(__file__).resolve().parent / "astra-daemon"

def start():
    return subprocess.Popen([str(BINARY)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

def request(process, payload):
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()
    assert select.select([process.stdout], [], [], 5)[0], "RPC response timed out"
    reply = json.loads(process.stdout.readline())
    assert reply["id"] == payload.get("id"), reply
    return reply

checks = 0
p = start()
try:
    for i in range(3):
        assert request(p, {"id": i, "op": "status"})["ok"]
        checks += 1
    for payload in [
        {"op": "bad"},
        {"op": "input", "keys": ["bad"]},
        {"op": "input", "duration_ms": -1},
        {"op": "input", "duration_ms": True},
        {"op": "input", "focus": 1},
        {"op": "input", "unexpected": 1},
        {"op": "step", "frames": 0},
        {"op": "step", "keys": ["n"]},
    ]:
        assert not request(p, {"id": "invalid", **payload})["ok"]
        checks += 1
    with tempfile.TemporaryDirectory(prefix="astra-daemon-smoke-") as directory:
        for i in range(2):
            path = Path(directory) / f"frame-{i}.png"
            result = request(p, {"id": "capture", "op": "capture", "output": str(path), "crop_top": 32})
            assert result["ok"] and path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", result
            checks += 1
finally:
    p.stdin.close()
    p.wait(timeout=2)
assert p.returncode == 0
checks += 1
for sig in (signal.SIGINT, signal.SIGTERM):
    p = start()
    request(p, {"id": "ready", "op": "status"})
    p.send_signal(sig)
    p.wait(timeout=2)
    assert p.returncode == 128 + sig
    p.stdin.close()
    checks += 1
print(f"{checks} daemon smoke checks passed (no controls sent)")
