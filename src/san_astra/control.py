from __future__ import annotations

import configparser
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from contextlib import contextmanager


DEFAULT_MAPPING = {
    "cross": "K", "square": "J", "triangle": "I", "circle": "L",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "l1": "Q", "r1": "E", "l2": "1", "r2": "3",
    "start": "Return", "select": "Backspace",
    "steer_left": "A", "steer_right": "D",
    "move_forward": "W", "move_backward": "S", "l_up": "W", "l_down": "S",
    "l3": "2", "r3": "4", "look_up": "T", "look_down": "G", "look_left": "F", "look_right": "H",
}
INI_BUTTONS = {
    "Cross": "cross", "Square": "square", "Triangle": "triangle", "Circle": "circle",
    "Left": "left", "Right": "right", "Up": "up", "Down": "down",
    "L1": "l1", "R1": "r1", "L2": "l2", "R2": "r2", "Start": "start", "Select": "select",
    "LLeft": "steer_left", "LRight": "steer_right",
    "LUp": "move_forward", "LDown": "move_backward", "L3": "l3", "R3": "r3",
    "RUp": "look_up", "RDown": "look_down", "RLeft": "look_left", "RRight": "look_right",
}


class ControlError(RuntimeError):
    pass


def config_path() -> Path:
    override = os.environ.get("SAN_ASTRA_PCSX2_INI") or os.environ.get("SAN_ASTRA_CONFIG")
    if override:
        return Path(override)
    isolated = Path(__file__).resolve().parents[2] / ".runtime/pcsx2/inis/PCSX2.ini"
    return isolated if isolated.exists() else Path.home() / "Library/Application Support/PCSX2/inis/PCSX2.ini"


def read_mapping(path: Path | None = None) -> tuple[dict, str]:
    path = path or config_path()
    mapping = DEFAULT_MAPPING.copy()
    if not path.exists():
        return mapping, "defaults (PCSX2 configuration not found)"
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path)
    for ini_name, name in INI_BUTTONS.items():
        value = parser.get("Pad1", ini_name, fallback="")
        # Multiple bindings are joined with '&'. Only keyboard bindings can be injected.
        keyboard = next((x.strip().removeprefix("Keyboard/") for x in value.split("&") if x.strip().startswith("Keyboard/")), None)
        if keyboard:
            mapping[name] = keyboard
        elif parser.has_section("Pad1"):
            mapping[name] = None
    mapping["l_up"] = mapping["move_forward"]
    mapping["l_down"] = mapping["move_backward"]
    return mapping, str(path)


class Controller:
    def __init__(self, bridge: Path | None = None, run_dir: Path | None = None, window_id: int | None = None, frame_stride: int | None = None, crop_top: int | None = None):
        self.crop_top = crop_top if crop_top is not None else int(os.environ.get("SAN_ASTRA_CROP_TOP", "32"))
        if isinstance(self.crop_top, bool) or not isinstance(self.crop_top, int) or not 0 <= self.crop_top <= 4096:
            raise ValueError("crop_top must be an integer between 0 and 4096")
        self.default_frame_stride = frame_stride if frame_stride is not None else int(os.environ.get("SAN_ASTRA_FRAME_STRIDE", "5"))
        if isinstance(self.default_frame_stride, bool) or not isinstance(self.default_frame_stride, int) or not 1 <= self.default_frame_stride <= 120:
            raise ValueError("frame_stride must be an integer between 1 and 120")
        self.bridge = Path(bridge or os.environ.get("SAN_ASTRA_BRIDGE", Path(__file__).resolve().parents[2] / "native/astra-bridge"))
        self.run_dir = Path(run_dir or os.environ.get("SAN_ASTRA_RUN_DIR", "runs"))
        self.window_id = window_id or (int(os.environ["SAN_ASTRA_WINDOW_ID"]) if os.environ.get("SAN_ASTRA_WINDOW_ID") else None)
        self.config_path = config_path()
        self.mapping, self.mapping_source = read_mapping(self.config_path)
        self.session = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]

    def call(self, *args: str) -> dict:
        try:
            result = subprocess.run([str(self.bridge), *args], text=True, capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ControlError(f"Native bridge failed: {exc}") from exc
        if result.returncode:
            raise ControlError(result.stderr.strip() or result.stdout.strip() or f"Bridge exited {result.returncode}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ControlError(f"Bridge returned invalid JSON: {result.stdout[:200]}") from exc

    @contextmanager
    def lock(self):
        # Shared across every run directory and MCP/CLI process for this user.
        lock_path = Path(os.environ.get("SAN_ASTRA_LOCK", str(Path.home() / ".san-astra/control.lock")))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ControlError("Another San Astra action is in progress; retry after it completes") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def record(self, data: dict):
        directory = self.run_dir / self.session
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "events.jsonl").open("a") as handle:
            handle.write(json.dumps({"timestamp": time.time(), **data}) + "\n")

    def frame_advance_binding(self):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(self.config_path)
        binding = parser.get("Hotkeys", "FrameAdvance", fallback="")
        return binding

    def doctor(self):
        binding = self.frame_advance_binding()
        configured = binding.strip().lower() == "keyboard/n"
        return {"bridge": str(self.bridge), "status": self.call("status"), "windows": self.call("windows"), "default_frame_stride": self.default_frame_stride, "crop_top": self.crop_top, "mapping": self.mapping, "mapping_source": self.mapping_source, "frame_advance_binding": binding, "frame_advance_configured": configured, "warnings": [] if configured else ["FrameAdvance is not configured as Keyboard/N in this profile; step may not advance emulation. Run setup and launch the isolated profile."], "observation_contract": "Screen pixels only; no game memory, position, speed, or telemetry."}

    def _observe(self):
        directory = (self.run_dir / self.session).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"frame-{time.time_ns()}.png"
        args = ["capture", "--output", str(output), "--crop-top", str(self.crop_top)]
        if self.window_id is not None:
            args.extend(["--window-id", str(self.window_id)])
        started = time.monotonic()
        native = self.call(*args)
        if not output.is_file():
            raise ControlError(f"Bridge did not create screenshot: {output}")
        data = {"type": "observation", "image_path": str(output), "capture_ms": round((time.monotonic() - started) * 1000, 2), "native": native}
        self.record(data)
        return data

    def observe(self):
        with self.lock():
            return self._observe()

    def release(self):
        # Emergency release intentionally bypasses the action lock.
        return self.call("release")

    def action(self, buttons: list[str] | None = None, duration_ms: int = 150, throttle: bool = False, brake: bool = False, steer: str = "center", handbrake: bool = False):
        return self._execute(buttons, duration_ms, throttle, brake, steer, handbrake)

    def step(self, buttons: list[str] | None = None, frames: int | None = None, throttle: bool = False, brake: bool = False, steer: str = "center", handbrake: bool = False):
        frames = self.default_frame_stride if frames is None else frames
        if isinstance(frames, bool) or not isinstance(frames, int) or not 1 <= frames <= 120:
            raise ValueError("frames must be an integer between 1 and 120")
        if self.frame_advance_binding().strip().lower() != "keyboard/n":
            raise ControlError("step requires FrameAdvance = Keyboard/N in the selected PCSX2 profile. Run setup, launch that profile, and pause emulation before stepping.")
        return self._execute(buttons, 150, throttle, brake, steer, handbrake, frames)

    def _execute(self, buttons, duration_ms, throttle, brake, steer, handbrake, frames=None):
        if buttons is not None and (not isinstance(buttons, list) or any(not isinstance(button, str) for button in buttons)):
            raise ValueError("buttons must be a list of button name strings")
        if any(not isinstance(value, bool) for value in (throttle, brake, handbrake)):
            raise ValueError("throttle, brake, and handbrake must be booleans")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or not 50 <= duration_ms <= 2000:
            raise ValueError("duration_ms must be an integer between 50 and 2000")
        if steer not in ("left", "center", "right"):
            raise ValueError("steer must be left, center, or right")
        names = list(buttons or [])
        names += (["cross"] if throttle else []) + (["square"] if brake else []) + (["r1"] if handbrake else [])
        if steer != "center":
            names.append("steer_" + steer)
        unknown = set(names) - self.mapping.keys()
        if unknown:
            raise ValueError(f"Unknown buttons: {sorted(unknown)}. Allowed: {sorted(self.mapping)}")
        names = list(dict.fromkeys(names))
        unavailable = [name for name in names if not self.mapping[name]]
        if unavailable:
            raise ControlError(f"No keyboard binding configured for {unavailable} in {self.mapping_source}; run setup or configure those Pad1 bindings.")
        keys = list(dict.fromkeys(self.mapping[name].lower() for name in names))
        with self.lock():
            started = time.monotonic()
            event = {"type": "action", "buttons": names, "keys": keys, "duration_ms": duration_ms}
            try:
                if frames is None:
                    if keys:
                        event["native"] = self.call("input", "--keys", ",".join(keys), "--duration-ms", str(duration_ms), "--focus")
                    else:
                        self.release()
                        time.sleep(duration_ms / 1000)
                        event["native"] = {"ok": True, "neutral": True}
                else:
                    event.update(type="step", frames=frames)
                    event.pop("duration_ms")
                    event["native"] = self.call("step", "--keys", ",".join(keys), "--frames", str(frames), "--frame-key", "n", "--frame-interval-ms", "35")
            except BaseException as exc:
                event["error"] = str(exc)
                # A failed or interrupted bridge may leave remapped keys down.
                # Release only keys this operation attempted to inject; successful
                # native operations already release their keys internally.
                if keys:
                    try:
                        self.call("release", "--keys", ",".join(keys))
                    except ControlError as release_exc:
                        event["release_error"] = str(release_exc)
                raise
            finally:
                event["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
                self.record(event)
            observation = self._observe()
            return {"action": event, "observation": observation}
