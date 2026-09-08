#!/usr/bin/env python3
"""Read-only regression: simultaneous daemon clients capturing explicit PCSX2 PIDs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import select
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--pids", type=int, nargs="+", required=True)
parser.add_argument("--rounds", type=int, default=2)
args = parser.parse_args()
binary = Path(__file__).resolve().parent / "astra-daemon"


def probe(pid, directory):
    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, bufsize=1)
    results = []
    try:
        for index in range(args.rounds + 1):
            op = "status" if index == 0 else "capture"
            request = {"id": index, "op": op, "pid": pid}
            path = Path(directory) / f"{pid}-{index}.png"
            if op == "capture":
                request.update(output=str(path), crop_top=32)
            started = time.monotonic()
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            assert select.select([process.stdout], [], [], 12)[0], f"{pid}: {op} timeout"
            reply = json.loads(process.stdout.readline())
            assert reply.get("ok") and reply.get("id") == index and reply.get("pid") == pid, reply
            if op == "capture":
                assert reply["capture_backend"] == "serialized-one-shot", reply
                assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            results.append({"pid": pid, "op": op, "elapsed_ms": round((time.monotonic()-started)*1000, 2)})
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=2)
    return results

with tempfile.TemporaryDirectory(prefix="astra-multiprocess-") as directory:
    with ThreadPoolExecutor(max_workers=len(args.pids)) as pool:
        results = list(pool.map(lambda pid: probe(pid, directory), args.pids))
print(json.dumps({"ok": True, "controls_sent": False, "checks": sum(map(len, results)), "results": results}, indent=2))
