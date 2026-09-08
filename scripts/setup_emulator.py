#!/usr/bin/env python3
"""Create an isolated PCSX2 profile; optionally launch a user's local game dump."""
from __future__ import annotations

import argparse
import configparser
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path.home() / "Library/Application Support/PCSX2"


WRITABLE_FOLDERS = {
    "Snapshots": "snaps", "Savestates": "sstates", "MemoryCards": "memcards",
    "Logs": "logs", "Cheats": "cheats", "Patches": "patches",
    "UserResources": "resources", "Cache": "cache", "Textures": "textures",
    "InputProfiles": "inputprofiles", "Videos": "videos",
    "DebuggerLayouts": "debuggerlayouts", "DebuggerSettings": "debuggersettings",
}
KEYBOARD = {
    "Cross": "K", "Square": "J", "Triangle": "I", "Circle": "L",
    "Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down",
    "L1": "Q", "R1": "E", "L2": "1", "R2": "3", "L3": "2", "R3": "4",
    "Start": "Return", "Select": "Backspace", "LLeft": "A", "LRight": "D",
    "LUp": "W", "LDown": "S", "RUp": "T", "RDown": "G", "RLeft": "F", "RRight": "H",
}


def read_config(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    config.read(path)
    return config


def prepare(source: Path, target: Path) -> Path:
    source, target = source.expanduser().resolve(), target.expanduser().resolve()
    if source == target:
        raise ValueError("The experiment profile must differ from the source PCSX2 profile")
    if target.name.lower() != "pcsx2":
        raise ValueError("On macOS --profile must end with PCSX2 (case insensitive)")
    ini = target / "inis/PCSX2.ini"
    if not ini.resolve().is_relative_to(target):
        raise ValueError("Isolated configuration resolves outside profile")
    original = source / "inis/PCSX2.ini"
    if not original.is_file() and not ini.is_file():
        raise ValueError(f"PCSX2 configuration missing: {original}. Complete PCSX2 setup first.")
    # Reconcile required experiment settings on every run; retain other isolated settings.
    config = read_config(ini if ini.is_file() else original)
    bios_config = read_config(original) if original.is_file() else config
    bios_base = source if original.is_file() else target
    bios_dir = Path(bios_config.get("Folders", "Bios", fallback="bios")).expanduser()
    bios_dir = (bios_dir if bios_dir.is_absolute() else bios_base / bios_dir).resolve()
    bios = Path(bios_config.get("Filenames", "BIOS", fallback="")).expanduser()
    bios = (bios if bios.is_absolute() else bios_dir / bios).resolve()
    if not bios.is_file() or bios.stat().st_size < 1024 * 1024:
        raise ValueError(f"Configured BIOS is missing or incomplete: {bios}")
    folders = {"Bios": str(bios.parent)}
    for name, default in WRITABLE_FOLDERS.items():
        current = Path(config.get("Folders", name, fallback=default)).expanduser()
        current = (current if current.is_absolute() else target / current).resolve()
        destination = current if current.is_relative_to(target) else (target / default).resolve()
        if not destination.is_relative_to(target):
            raise ValueError(f"Isolated {name} directory resolves outside profile: {destination}")
        folders[name] = str(destination)
    settings = {
        "UI": {"StartPaused": "true", "PauseOnFocusLoss": "false", "RenderToSeparateWindow": "true", "HideMainWindowWhenRunning": "true", "ConfirmShutdown": "true"},
        "Folders": folders,
        "Filenames": {"BIOS": bios.name},
        "EmuCore": {"EnablePINE": "false", "EnableCheats": "false"},
        "Pad1": {"Type": "DualShock2", **{button: "Keyboard/" + key for button, key in KEYBOARD.items()}},
    }
    # Remove custom conflicting hotkeys before installing explicit experiment bindings.
    hotkeys = {key: "" for key in config["Hotkeys"]} if config.has_section("Hotkeys") else {}
    hotkeys.update(FrameAdvance="Keyboard/N", TogglePause="Keyboard/Space",
                   ToggleFullscreen="Keyboard/Alt & Keyboard/Return",
                   SaveStateToSlot="Keyboard/F1", LoadStateFromSlot="Keyboard/F3",
                   NextSaveStateSlot="Keyboard/F2", Screenshot="Keyboard/F8",
                   OpenPauseMenu="Keyboard/Escape")
    settings["Hotkeys"] = hotkeys
    for section, values in settings.items():
        if not config.has_section(section):
            config.add_section(section)
        config[section].update(values)
    if config.has_section("MemoryCards"):
        for name, value in list(config["MemoryCards"].items()):
            if name.endswith("_Filename") and value:
                card = Path(value).expanduser()
                resolved = (card if card.is_absolute() else Path(folders["MemoryCards"]) / card).resolve()
                if not resolved.is_relative_to(target):
                    # Never copy, overwrite, or point at an original user card.
                    replacement = Path(folders["MemoryCards"]) / card.name
                    if not replacement.resolve().is_relative_to(target):
                        raise ValueError(f"Isolated memory card resolves outside profile: {replacement}")
                    config["MemoryCards"][name] = card.name
    ini.parent.mkdir(parents=True, exist_ok=True)
    for name in WRITABLE_FOLDERS:
        Path(folders[name]).mkdir(parents=True, exist_ok=True)
    temporary = ini.with_suffix(".ini.tmp")
    with temporary.open("w") as stream:
        config.write(stream)
    temporary.replace(ini)
    return ini


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--profile", type=Path, default=ROOT / ".runtime/pcsx2")
    parser.add_argument("--app", type=Path, default=Path("/Applications/PCSX2-v2.8.2.app"))
    parser.add_argument("--iso", type=Path)
    parser.add_argument("--bios", action="store_true", help="Boot BIOS for control smoke test")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--statefile", type=Path)
    args = parser.parse_args()
    if args.iso:
        args.iso = args.iso.expanduser().resolve()
        if not args.iso.is_file() or args.iso.stat().st_size < 1024 * 1024:
            parser.error(f"Game image missing or incomplete: {args.iso}")
        if args.iso.with_suffix(args.iso.suffix + ".part").exists():
            parser.error("Download .part file still exists; wait for download completion")
    if args.launch and not (args.iso or args.bios):
        parser.error("--launch requires --iso PATH or --bios")
    if args.statefile and not args.statefile.is_file():
        parser.error("--statefile does not exist")
    if args.bios and args.iso:
        parser.error("Choose either --bios or --iso")
    if args.launch:
        if not (args.app.expanduser() / "Contents/MacOS/PCSX2").is_file():
            parser.error(f"PCSX2 executable missing in {args.app}")
        existing = subprocess.run(["pgrep", "-x", "PCSX2"], capture_output=True, text=True)
        if existing.returncode == 0:
            parser.error("PCSX2 is already running. Quit it before launching the isolated profile.")
    try:
        ini = prepare(args.source, args.profile)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    # On macOS PCSX2 appends "PCSX2" to -datapath (the application-data base).
    if ini.parent.parent.name.lower() != "pcsx2":
        parser.error("On macOS --profile must end with PCSX2 (case insensitive)")
    cmd = [str(args.app.expanduser().resolve() / "Contents/MacOS/PCSX2"), "-datapath", str(ini.parent.parent.parent)]
    if args.bios:
        cmd += ["-bios"]
    if args.statefile:
        cmd += ["-statefile", str(args.statefile.resolve())]
    if args.iso:
        cmd += ["-fastboot", "--", str(args.iso)]
    result = {"profile": str(ini.parent.parent), "ini": str(ini), "command": cmd,
              "frame_advance": "n", "starts_paused": True}
    if args.launch:
        log = ini.parent.parent / "launch.log"
        with log.open("a") as stream:
            child = subprocess.Popen(cmd, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        result.update(pid=child.pid, log=str(log))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
