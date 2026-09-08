#!/usr/bin/env python3
"""Capture emulator display frames with PCSX2, then export PNGs and realtime playback.

The master MKV comes from PCSX2's GS/VSync capture path, not desktop polling.
The setup script configures FFV1/bgr0 lossless video and the F12 toggle hotkey.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / ".runtime/pcsx2"


def status(profile: Path = DEFAULT_PROFILE) -> dict:
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(profile / "inis/PCSX2.ini")
    folder = Path(config.get("Folders", "Videos", fallback="videos"))
    folder = folder if folder.is_absolute() else profile / folder
    keys = ["EnableVideoCapture", "EnableAudioCapture", "CaptureContainer", "VideoCaptureCodec",
            "VideoCaptureFormat", "VideoCaptureAutoResolution"]
    return {"profile": str(profile.resolve()), "directory": str(folder.resolve()),
            "toggle_binding": config.get("Hotkeys", "ToggleVideoCapture", fallback=""),
            "settings": {key: config.get("EmuCore/GS", key, fallback="") for key in keys},
            "recordings": [{"path": str(p.resolve()), "bytes": p.stat().st_size}
                           for p in sorted(folder.glob("*.mkv"), key=lambda p: p.stat().st_mtime)],
            "note": "Files/settings only; this does not query whether capture is currently active."}


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    override = os.environ.get("SAN_ASTRA_FFMPEG")
    candidate = override or shutil.which("ffmpeg")
    if candidate:
        check = subprocess.run([candidate, "-version"], capture_output=True)
        if check.returncode == 0:
            return candidate
        if override:
            raise RuntimeError("SAN_ASTRA_FFMPEG executable failed its version check")
    # Isolated wheel fallback avoids modifying a broken system/Homebrew install.
    result = subprocess.run(["uv", "run", "--with", "imageio-ffmpeg", "python", "-c",
                             "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                            text=True, capture_output=True, check=True)
    return result.stdout.strip().splitlines()[-1]


def count_frames(source: Path) -> int:
    """Count stored video packets without decoding; a live MKV yields a lower bound.

    An empty/new header can legitimately expose no packets yet. Encoder and mux
    buffers mean this is not an acknowledgment of individual advance requests.
    """
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        return 0
    result = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(source),
                             "-map", "0:v:0", "-c", "copy", "-f", "null", "-",
                             "-progress", "pipe:1", "-nostats"],
                            text=True, capture_output=True, timeout=15)
    values = [int(line.split("=", 1)[1].strip()) for line in result.stdout.splitlines()
              if line.startswith("frame=") and line.split("=", 1)[1].strip().isdigit()]
    return max(values, default=0)


def toggle(profile: Path = DEFAULT_PROFILE) -> dict:
    from san_astra.control import Controller
    current = status(profile)
    if current["toggle_binding"].lower() != "keyboard/f12":
        raise ValueError("Reload the setup profile first; ToggleVideoCapture must be Keyboard/F12")
    controller = Controller()
    with controller.lock():
        result = controller.call("input", "--keys", "f12", "--duration-ms", "80", "--focus")
    return {"toggle_sent": True, "native": result, "video_directory": current["directory"],
            "note": "F12 toggles capture. Inspect the recording indicator/files; no active-state telemetry is read."}


def export(source: Path, output: Path | None = None) -> dict:
    source = source.expanduser().resolve()
    if not source.is_file() or not source.stat().st_size:
        raise ValueError("Provide a completed, nonempty PCSX2 capture file")
    output = (output or ROOT / "runs/recordings" / source.stem).expanduser().resolve()
    ignored_roots = [(ROOT / "runs").resolve(), (ROOT / ".runtime").resolve()]
    if not any(output.is_relative_to(root) for root in ignored_roots):
        raise ValueError("Recording output must be beneath this repository's Git-ignored runs/ or .runtime/")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Export directory already contains files; choose another directory")
    frames = output / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    original_signature = (source.stat().st_size, source.stat().st_mtime_ns)
    executable = ffmpeg_path()
    playback = output / "playback.mp4"
    command = [executable, "-hide_banner", "-nostdin", "-n", "-i", str(source),
               "-map", "0:v:0", "-c:v", "png", "-pix_fmt", "rgb24", "-fps_mode", "passthrough",
               str(frames / "frame-%08d.png"),
               "-map", "0:v:0", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-movflags", "+faststart",
               str(playback), "-progress", "pipe:1", "-nostats"]
    started = time.monotonic()
    result = subprocess.run(command, text=True, capture_output=True)
    (output / "ffmpeg.stdout").write_text(result.stdout)
    (output / "ffmpeg.stderr").write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f"Export failed; details in {output / 'ffmpeg.stderr'}")
    if (source.stat().st_size, source.stat().st_mtime_ns) != original_signature:
        raise RuntimeError("Master capture changed during export. Stop recording, then export to a new directory.")
    count = sum(1 for _ in frames.glob("frame-*.png"))
    if not count:
        raise RuntimeError("Capture decoded no video frames")
    with source.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    metadata = {"master": str(source), "master_sha256": checksum, "master_bytes": source.stat().st_size,
                "frames_directory": str(frames), "decoded_frame_count": count,
                "playback": str(playback), "playback_bytes": playback.stat().st_size,
                "export_elapsed_seconds": round(time.monotonic() - started, 3),
                "timing": "Playback preserves the capture's simulation timestamps; no desktop wall-time or inferred FPS is substituted.",
                "provenance": "Master retained unchanged; PNGs decode every stored frame. Completeness depends on successful PCSX2 native capture."}
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read configured capture settings and existing files")
    commands.add_parser("toggle", help="Send F12 to start/stop capture; coordinate with the active driver")
    count = commands.add_parser("count", help="Count stored video frames without decoding; live count is a lower bound")
    count.add_argument("source", type=Path)
    convert = commands.add_parser("export", help="After stopping capture, retain master and decode all frames plus MP4")
    convert.add_argument("source", type=Path)
    convert.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = (status(args.profile) if args.command == "status" else toggle(args.profile) if args.command == "toggle"
              else {"frames": count_frames(args.source), "note": "Live count is a buffered lower bound"} if args.command == "count"
              else export(args.source, args.output))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
