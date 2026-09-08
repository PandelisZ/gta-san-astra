#!/usr/bin/env python3
"""Run and record an autonomous, approximately one-minute simulation attempt.

Before default reset, quit PCSX2. With --no-reset the caller must have restored
the paused baseline and stopped recording. This script never chooses driving
buttons: all control phases come from Astra through autodrive.py.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

import recording
import scenario

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def new_recording(folder: Path, before: set[Path], timeout=15) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = set(folder.glob("*.mkv")) - before
        if len(candidates) > 1:
            raise RuntimeError("Multiple new recordings appeared; cannot identify this attempt")
        if candidates:
            return candidates.pop().resolve()
        time.sleep(0.1)
    raise RuntimeError("No new capture appeared; verify recording was OFF before the attempt")


def wait_finalized(path: Path, timeout=30):
    deadline, signature, changed = time.monotonic() + timeout, None, time.monotonic()
    while time.monotonic() < deadline:
        current = (path.stat().st_size, path.stat().st_mtime_ns)
        if current != signature:
            signature, changed = current, time.monotonic()
        elif current[0] > 0 and time.monotonic() - changed >= 1.5:
            return
        time.sleep(0.1)
    raise RuntimeError("Capture did not finalize within 30 seconds; master retained for recovery")


def media_duration(path: Path) -> float | None:
    probe = subprocess.run([recording.ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(path)],
                           text=True, capture_output=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr)
    return round(int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]), 3) if match else None


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def drive(command: list[str], log_path: Path, environment: dict) -> int:
    with log_path.open("x") as output:
        child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                 cwd=ROOT, env=environment, start_new_session=True)
        try:
            return child.wait()
        except BaseException:
            # Signal only this wrapper's owned driver/process group.
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            raise


def attempt(args) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.name):
        raise ValueError("Attempt name may contain letters, numbers, underscores and hyphens")
    directory = ROOT / "runs" / args.name
    video = ROOT / "docs/videos" / f"{args.name}.mp4"
    video_metadata = video.with_suffix(".json")
    if directory.exists() or video.exists() or video_metadata.exists():
        raise ValueError("Attempt name already exists; choose a new name to preserve previous evidence")
    if not 1 <= args.steps <= 10000:
        raise ValueError("steps must be between 1 and 10000")
    existing = subprocess.run(["pgrep", "-fl", r"(^|[ /])autodrive\.py([ ]|$)"], capture_output=True, text=True)
    target_pid = args.pid
    if existing.returncode == 0 and not (target_pid is not None or args.allow_multiple):
        raise RuntimeError("An autodrive process is already active; concurrent attempts require an explicit PID and separate profile.")
    if target_pid is not None and existing.returncode == 0 and re.search(r"--pid\s+" + str(target_pid) + r"(?:\s|$)", existing.stdout):
        raise RuntimeError("An autodrive process already targets this PCSX2 PID")
    if args.no_reset and args.allow_multiple and target_pid is None:
        raise ValueError("--no-reset --allow-multiple requires --pid or SAN_ASTRA_PID")
    if not args.no_reset and args.iso is None:
        raise ValueError("Reset requires --iso PATH, or use --no-reset after caller restoration")
    profile = args.profile.expanduser().resolve()
    if args.no_reset and target_pid is not None:
        from san_astra.processes import verify_profile_pid
        verify_profile_pid(target_pid, profile)
    statefile = args.scenarios.expanduser().resolve() / args.scenario / "state.p2s"
    manifest = {"name": args.name, "started_at": time.time(), "status": "preparing",
                "goal": args.goal, "scenario": args.scenario, "reset": not args.no_reset,
                "target_pid": target_pid, "profile": str(profile),
                "steps_budget": args.steps, "frames_per_decision": 60,
                "requested_vsync_budget": args.steps * 60,
                "nominal_seconds_budget": round(args.steps * 60 / 59.94, 3),
                "target_recorded_frames": 3597, "clip_seconds_limit": 60,
                "duration_note": "Stop after a whole burst crosses3597 stored frames (about one minute), with120 decisions as a safety cap. Live count is buffered, so the full recording can exceed one minute. Git replay contains its first60 real seconds with no padding; actual frame count and duration are measured.",
                "logic_sha256": {str(path.relative_to(ROOT)): file_sha256(path) for path in
                                 (ROOT / "scripts/autodrive.py", ROOT / "src/san_astra/policy.py")},
                "autonomy": "Astra chooses every driving control phase. Wrapper only handles reset, recording and export.",
                "git_video": str(video.relative_to(ROOT))}
    directory.mkdir(parents=True)
    manifest_path = directory / "attempt.json"
    write_json(manifest_path, manifest)
    recording_started, source, failure = False, None, None
    try:
        if not args.no_reset:
            manifest["reset_result"] = scenario.launch(args.scenario, args.iso, scenarios=args.scenarios,
                                                        profile=profile, allow_multiple=args.allow_multiple)
            target_pid = manifest["reset_result"]["pid"]
            if target_pid is None:
                raise RuntimeError("Scenario launcher did not report the new PCSX2 PID")
            manifest["target_pid"] = target_pid
            # Read-only readiness: do not send gameplay input while loading the snapshot.
            from san_astra.control import Controller
            controller = Controller(pid=target_pid, ini_path=profile / "inis/PCSX2.ini")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    windows = controller.call("windows").get("windows", [])
                    if any("grand theft auto" in window.get("title", "").lower() for window in windows):
                        break
                except RuntimeError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("PCSX2 window did not appear after scenario launch")
        capture = recording.status(profile)
        folder = Path(capture["directory"])
        before = set(folder.glob("*.mkv"))
        manifest["record_start"] = recording.toggle(profile, pid=target_pid)
        recording_started = True
        source = new_recording(folder, before)
        manifest.update(status="driving", master=str(source))
        write_json(manifest_path, manifest)
        print(json.dumps({"status": "driving", "run": str(directory), "master": str(source)}), flush=True)
        command = [sys.executable, str(ROOT / "scripts/autodrive.py"), "--run-dir", str(directory),
                   "--steps", str(args.steps), "--frame-stride", "60", "--mode", "stepped",
                   "--model", "gpt-6-astra", "--reasoning-effort", "low", "--service-tier", "fast",
                   "--policy-transport", "app-server", "--bridge-transport", "daemon",
                   "--vision-max-edge", str(args.vision_max_edge), "--goal", args.goal,
                   "--scenario-state", str(statefile), "--timeout", str(args.timeout),
                   "--recording-master", str(source), "--target-recorded-frames", "3597"]
        environment = {**os.environ, "SAN_ASTRA_PCSX2_INI": str(profile / "inis/PCSX2.ini")}
        if target_pid is not None:
            command.extend(["--pid", str(target_pid)])
            environment["SAN_ASTRA_PID"] = str(target_pid)
        manifest["driver_exit_code"] = drive(command, directory / "driver.stdout", environment)
        summary_path = directory / "run_summary.json"
        if summary_path.is_file():
            manifest["driver_summary"] = json.loads(summary_path.read_text())
        if manifest["driver_exit_code"]:
            failure = f"Autonomous driver exited {manifest['driver_exit_code']}; see driver.stdout"
    except BaseException as exc:
        failure = str(exc) or type(exc).__name__
    finally:
        if recording_started:
            try:
                manifest["record_stop"] = recording.toggle(profile, pid=target_pid)
            except BaseException as exc:
                manifest["record_stop_error"] = str(exc)
                failure = failure or f"Could not stop recording: {exc}"
        manifest.update(status="exporting" if source and "record_stop_error" not in manifest else "failed", error=failure)
        write_json(manifest_path, manifest)
    if source and "record_stop_error" not in manifest:
        try:
            wait_finalized(source)
            exported = recording.export(source, directory / "recording")
            playback = Path(exported["playback"])
            full_duration = media_duration(playback)
            replay = directory / "recording/first-minute.mp4"
            clip = subprocess.run([recording.ffmpeg_path(), "-hide_banner", "-nostdin", "-n", "-i", str(playback),
                                   "-map", "0:v:0", "-t", "60", "-c:v", "libx264", "-preset", "fast",
                                   "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
                                   "-movflags", "+faststart", str(replay)], text=True, capture_output=True)
            (directory / "recording/clip.stderr").write_text(clip.stderr)
            if clip.returncode:
                raise RuntimeError("Minute replay export failed; full recording is preserved")
            duration = media_duration(replay)
            video.parent.mkdir(parents=True, exist_ok=True)
            with replay.open("rb") as incoming, video.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            with video.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest.update(export=exported, decoded_frame_count=exported["decoded_frame_count"],
                            measured_video_duration_seconds=duration, video_sha256=checksum,
                            full_recording_duration_seconds=full_duration,
                            recorded_target_reached=exported["decoded_frame_count"] >= 3597,
                            git_video_frame_count=recording.count_frames(video),
                            measured_duration_source="MP4 container duration reported by FFmpeg",
                            status="failed" if failure else "completed", ended_at=time.time())
            # Only the compact replay and its provenance go in the Git-visible folder.
            with video_metadata.open("x") as stream:
                json.dump({key: manifest[key] for key in ("name", "goal", "scenario", "target_pid", "profile", "autonomy",
                    "requested_vsync_budget", "nominal_seconds_budget", "decoded_frame_count",
                    "target_recorded_frames", "recorded_target_reached", "full_recording_duration_seconds",
                    "clip_seconds_limit", "git_video_frame_count", "logic_sha256",
                    "measured_video_duration_seconds", "measured_duration_source", "duration_note",
                    "video_sha256", "status")}, stream, indent=2)
                stream.write("\n")
        except BaseException as exc:
            failure = failure or str(exc) or type(exc).__name__
            manifest.update(status="failed", error=failure, ended_at=time.time())
    write_json(manifest_path, manifest)
    if failure:
        raise RuntimeError(f"{failure}. Attempt evidence: {manifest_path}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=time.strftime("attempt-%Y%m%d-%H%M%S"))
    parser.add_argument("--scenario", default="quiet-tahoma")
    parser.add_argument("--scenarios", type=Path, default=scenario.DEFAULT_SCENARIOS, help="Shared immutable scenario directory, including across worktrees")
    parser.add_argument("--iso", type=Path)
    parser.add_argument("--profile", type=Path, default=recording.DEFAULT_PROFILE)
    parser.add_argument("--pid", type=int, default=int(os.environ["SAN_ASTRA_PID"]) if os.environ.get("SAN_ASTRA_PID") else None)
    parser.add_argument("--allow-multiple", action="store_true", help="Permit other instances using different profiles; --no-reset also requires an explicit PID")
    parser.add_argument("--no-reset", action="store_true", help="Caller already restored paused baseline and ensured recording is OFF")
    parser.add_argument("--steps", type=int, default=120, help="Decision safety cap; recording target is3597 stored frames")
    parser.add_argument("--vision-max-edge", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--goal", default="Drive around one city block and return visibly to the starting landmark and orientation. Choose all driving actions autonomously from screenshots; avoid obstacles and pedestrians and recover when necessary.")
    args = parser.parse_args()
    profile_key = hashlib.sha256(str(args.profile.expanduser().resolve()).encode()).hexdigest()[:16]
    lock_path = Path.home() / f".san-astra/attempt-{profile_key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = attempt(args)
            print(json.dumps(result, indent=2))
        except (ValueError, RuntimeError, OSError) as exc:
            parser.exit(1, json.dumps({"error": str(exc)}) + "\n")


if __name__ == "__main__":
    main()
