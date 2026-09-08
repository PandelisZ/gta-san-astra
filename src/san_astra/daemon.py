"""Warm JSONL native transport; Controller retains validation and the global lock."""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import threading

from .control import Controller, ControlError


class DaemonClient:
    def __init__(self, command: list[str] | None = None, timeout: float = 15):
        default = Path(__file__).resolve().parents[2] / "native/astra-daemon"
        self.command = command or [os.environ.get("SAN_ASTRA_DAEMON", str(default))]
        self.timeout = timeout
        self.process = None
        self._stderr = tempfile.TemporaryFile(mode="w+")
        self._serial = threading.Lock()
        self._counter = 0
        self._closed = False

    def request(self, operation: str, **fields) -> dict:
        with self._serial:
            if self._closed:
                raise ControlError("Native daemon transport is closed")
            if self.process is None:
                try:
                    self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=self._stderr, text=True, bufsize=1)
                except OSError as exc:
                    raise ControlError(f"Cannot start native daemon; run sh native/build-daemon.sh: {exc}") from exc
            process = self.process
            self._counter += 1
            request_id = self._counter
            try:
                process.stdin.write(json.dumps({"id": request_id, "op": operation, **fields}) + "\n")
                process.stdin.flush()
                if not select.select([process.stdout], [], [], self.timeout)[0]:
                    raise ControlError(f"Native daemon timed out after {self.timeout} seconds")
                line = process.stdout.readline()
                if not line:
                    self._stderr.seek(0)
                    raise ControlError("Native daemon disconnected: " + self._stderr.read()[-1000:])
                reply = json.loads(line)
                if not isinstance(reply, dict) or reply.get("id") != request_id:
                    raise ControlError("Native daemon response ID did not match request")
            except (OSError, ValueError, ControlError, KeyboardInterrupt) as exc:
                self.close()
                if isinstance(exc, (ControlError, KeyboardInterrupt)):
                    raise
                raise ControlError(f"Native daemon protocol failed: {exc}") from exc
            if reply.get("ok") is not True:
                raise ControlError(str(reply.get("error", "Native daemon operation failed")))
            return reply

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.process is not None:
            # EOF releases native active keys; terminate also invokes its cleanup handler.
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process.stdout.close()
        self._stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class DaemonController(Controller):
    """Reuse normal Controller behavior with a persistent native process."""
    def __init__(self, *args, daemon_client: DaemonClient | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon_client = daemon_client or DaemonClient()

    def call(self, *args: str) -> dict:
        args = self.target_args(args)
        with self.actuation_lock(args):
            return self._call_daemon(*args)

    def _call_daemon(self, *args: str) -> dict:
        if not args:
            raise ControlError("Native daemon operation is required")
        fields = {}
        integers = {"pid", "window_id", "crop_top", "duration_ms", "frames", "frame_interval_ms"}
        allowed = integers | {"output", "keys", "frame_key"}
        index = 1
        while index < len(args):
            flag = args[index]
            if flag in ("--focus", "--no-focus"):
                fields[flag.removeprefix("--").replace("-", "_")] = True
                index += 1
                continue
            name = flag.removeprefix("--").replace("-", "_")
            if not flag.startswith("--") or name not in allowed or index + 1 >= len(args):
                raise ControlError(f"Unsupported native daemon argument: {flag}")
            value = args[index + 1]
            fields[name] = int(value) if name in integers else value.split(",") if name == "keys" and value else [] if name == "keys" else value
            index += 2
        return self.daemon_client.request(args[0], **fields)

    def close(self):
        self.daemon_client.close()
