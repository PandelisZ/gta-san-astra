#!/usr/bin/env python3
"""Capture and relaunch opaque PCSX2 scenarios. Pause the emulator before capture.

Savestates are reset artifacts only: their contents are never parsed or sent to
the driving policy. The policy receives game screenshots, never savestate data.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from san_astra.control import Controller, ControlError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / ".runtime/scenarios"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def destination(root: Path, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        raise ValueError("Scenario name must contain only letters, numbers, underscores or hyphens")
    root = root.resolve()
    target = root / name
    if target.is_symlink():
        raise ValueError("Scenario destination cannot be a symlink")
    return target


def state_files(directory: Path) -> dict[Path, tuple[int, int]]:
    return {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in directory.glob("*.p2s") if p.is_file() and not p.is_symlink()}


def wait_for_save(directory: Path, before: dict, timeout: float = 15.0) -> Path:
    deadline = time.monotonic() + timeout
    stable: dict[Path, tuple[tuple[int, int], float]] = {}
    while time.monotonic() < deadline:
        current = state_files(directory)
        changed = [path for path, signature in current.items() if signature != before.get(path) and signature[1] > 0]
        if len(changed) > 1:
            raise ControlError("Multiple savestates changed during capture; cannot identify the requested slot safely")
        for path in changed:
            signature = current[path]
            prior = stable.get(path)
            if prior and prior[0] == signature and time.monotonic() - prior[1] >= 0.75:
                return path
            if not prior or prior[0] != signature:
                stable[path] = (signature, time.monotonic())
        time.sleep(0.1)
    raise ControlError("No new or updated stable .p2s savestate appeared; ensure the game is running, paused, and F1 saves a state")


def capture(controller: Controller, name: str = "stationary-car", scenarios: Path = DEFAULT_SCENARIOS,
            replace: bool = False, iso: Path | None = None, timeout: float = 15.0) -> dict:
    """Caller must pause emulation and visually position the vehicle before capture."""
    target = destination(scenarios, name)
    if target.exists() and not replace:
        raise ValueError(f"Scenario already exists: {target}; use --replace explicitly")
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(controller.config_path)
    if config.get("Hotkeys", "SaveStateToSlot", fallback="").strip().lower() != "keyboard/f1":
        raise ControlError("Capture requires SaveStateToSlot = Keyboard/F1 in the selected profile")
    profile = controller.config_path.resolve().parent.parent
    if profile == (Path.home() / "Library/Application Support/PCSX2").resolve():
        raise ControlError("Capture requires the isolated experiment profile; run setup first")
    folder = Path(config.get("Folders", "Savestates", fallback="sstates")).expanduser()
    folder = (folder if folder.is_absolute() else profile / folder).resolve()
    if not folder.is_relative_to(profile):
        raise ControlError("Refusing to save outside the isolated emulator profile")
    if iso is not None and not iso.is_file():
        raise ValueError(f"Game image does not exist: {iso}")
    folder.mkdir(parents=True, exist_ok=True)
    scenarios.mkdir(parents=True, exist_ok=True)
    with controller.lock():
        before = state_files(folder)
        try:
            controller.call("input", "--keys", "f1", "--duration-ms", "80", "--focus")
        except BaseException:
            try:
                controller.call("release", "--keys", "f1")
            except ControlError:
                pass
            raise
        source = wait_for_save(folder, before, timeout)
        staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=scenarios))
        try:
            copied = staging / "state.p2s"
            shutil.copy2(source, copied)
            source_hash = digest(source)
            if digest(copied) != source_hash:
                raise ControlError("Savestate changed while copying; capture again")
            observation = controller._observe()
            shutil.copy2(observation["image_path"], staging / "frame.png")
            manifest = {
                "schema_version": 1, "name": name, "created_at": time.time(),
                "state_file": "state.p2s", "state_sha256": source_hash, "state_bytes": copied.stat().st_size,
                "source_slot_path": str(source), "frame_file": "frame.png",
                "config_filename": controller.config_path.name, "config_sha256": digest(controller.config_path),
                "game_filename": iso.name if iso else None,
                "capture_precondition": "Caller paused emulation and visually positioned the scene; no paused state or stationary speed inferred from memory.",
                "pixel_only_invariant": "Savestate is an opaque reset artifact. Never parse its contents or provide it to the driving policy. Policy observations are game screenshots only.",
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            # Existing scenarios change only after every new artifact is complete.
            if target.exists():
                if not replace:
                    raise ValueError("Scenario appeared during capture; refusing replacement")
                backup = target.with_name(f".{name}-previous-{time.time_ns()}")
                target.rename(backup)
                try:
                    staging.rename(target)
                except BaseException:
                    backup.rename(target)
                    raise
                shutil.rmtree(backup)
            else:
                staging.rename(target)
            return {"scenario": str(target), "manifest": manifest}
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def launch(name: str, iso: Path, scenarios: Path = DEFAULT_SCENARIOS, profile: Path | None = None) -> dict:
    """Launch a stopped PCSX2 using the immutable statefile, never an unknown slot."""
    target = destination(scenarios, name)
    manifest = json.loads((target / "manifest.json").read_text())
    state = target / "state.p2s"
    if state.is_symlink() or digest(state) != manifest["state_sha256"]:
        raise ControlError("Scenario savestate integrity check failed")
    iso = iso.expanduser().resolve()
    if not iso.is_file():
        raise ValueError(f"Game image does not exist: {iso}")
    if manifest.get("game_filename") and iso.name != manifest["game_filename"]:
        raise ValueError("Game filename differs from the captured scenario")
    if subprocess.run(["pgrep", "-x", "PCSX2"], capture_output=True).returncode == 0:
        raise ControlError("PCSX2 is running. Quit it before launching this scenario; live slots are never overwritten.")
    args = [sys.executable, str(ROOT / "scripts/setup_emulator.py"), "--iso", str(iso), "--statefile", str(state), "--launch"]
    if profile:
        args.extend(["--profile", str(profile)])
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise ControlError(result.stderr.strip() or result.stdout.strip())
    return {"scenario": str(target), "statefile": str(state), "launcher_output": result.stdout.strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("capture", help="Save current paused visual scene")
    save.add_argument("name", nargs="?", default="stationary-car")
    save.add_argument("--replace", action="store_true")
    save.add_argument("--iso", type=Path)
    restore = commands.add_parser("launch", help="Launch a scenario; requires PCSX2 stopped")
    restore.add_argument("name", nargs="?", default="stationary-car")
    restore.add_argument("--iso", type=Path, required=True)
    restore.add_argument("--profile", type=Path)
    args = parser.parse_args()
    try:
        result = capture(Controller(), args.name, args.scenarios, args.replace, args.iso) if args.command == "capture" else launch(args.name, args.iso, args.scenarios, args.profile)
        print(json.dumps(result, indent=2))
    except (ControlError, ValueError, OSError) as exc:
        parser.exit(1, json.dumps({"error": str(exc)}) + "\n")


if __name__ == "__main__":
    main()
