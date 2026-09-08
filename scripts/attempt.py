#!/usr/bin/env python3
"""Run and record an autonomous, bounded simulation attempt.

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
    if not 1 <= args.frame_stride <= 120:
        raise ValueError("frame stride must be between 1 and 120")
    if args.mode not in ("stepped", "burst", "flow"):
        raise ValueError("mode must be stepped, burst or flow")
    if args.mode in ("burst", "flow") and args.bridge_transport != "cli":
        raise ValueError("burst mode requires --bridge-transport cli")
    if not 1 <= args.target_recorded_frames <= 7193:
        raise ValueError("target recorded frames must be between 1 and 7193")
    if args.resume_from is not None and not args.no_reset:
        raise ValueError("Visual continuation requires --no-reset; stale context cannot follow a baseline reset")
    start_reference = args.start_reference
    if start_reference is None and args.resume_from is not None:
        prior_manifest = args.resume_from.expanduser().resolve() / "run_manifest.json"
        if prior_manifest.is_file():
            start_reference = json.loads(prior_manifest.read_text()).get("start_reference")
    if start_reference is not None:
        start_reference = Path(start_reference).expanduser().resolve()
        if not start_reference.is_file():
            raise ValueError(f"Starting screenshot reference does not exist: {start_reference}")
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
                "steps_budget": args.steps, "frames_per_decision": args.frame_stride, "mode": args.mode,
                "frame_budget_note": "Nominal wall-time frame budget; actual output comes from recording" if args.mode == "burst" else "Requested VSync budget",
                "requested_vsync_budget": args.steps * args.frame_stride,
                "nominal_seconds_budget": round(args.steps * args.frame_stride / 59.94, 3),
                "target_recorded_frames": args.target_recorded_frames, "clip_seconds_limit": 60,
                "duration_note": "Stop after a whole burst crosses the configured stored-frame target, with a decision safety cap. Live count is buffered, so full recording can exceed the target. Git replay contains up to its first60 real seconds with no padding; actual frame count and duration are measured.",
                "resume_from": str(args.resume_from.resolve()) if args.resume_from else None,
                "start_reference": str(start_reference) if start_reference else None,
                "logic_sha256": {str(path.relative_to(ROOT)): file_sha256(path) for path in
                                 (ROOT / "scripts/autodrive.py", ROOT / "src/san_astra/policy.py")},
                "autonomy": "Astra chooses every driving control phase. Wrapper only handles reset, recording and export.",
                "git_video": str(video.relative_to(ROOT))}
    directory.mkdir(parents=True)
    manifest_path = directory / "attempt.json"
    write_json(manifest_path, manifest)
    recording_started, source, failure = False, None, None
    screen_process, screen_log = None, None
    screen_movie = directory / "wall-clock.mov"
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
                   "--steps", str(args.steps), "--frame-stride", str(args.frame_stride), "--mode", args.mode,
                   "--model", "gpt-6-astra", "--reasoning-effort", "low", "--service-tier", "fast",
                   "--policy-transport", "app-server", "--bridge-transport", args.bridge_transport,
                   "--vision-max-edge", str(args.vision_max_edge), "--goal", args.goal,
                   "--scenario-state", str(statefile), "--timeout", str(args.timeout),
                   "--recording-master", str(source), "--target-recorded-frames", str(args.target_recorded_frames)]
        environment = {**os.environ, "SAN_ASTRA_PCSX2_INI": str(profile / "inis/PCSX2.ini")}
        if target_pid is not None:
            command.extend(["--pid", str(target_pid)])
            environment["SAN_ASTRA_PID"] = str(target_pid)
        if args.resume_from is not None:
            command.extend(["--resume-from", str(args.resume_from.resolve())])
        if start_reference is not None:
            command.extend(["--start-reference", str(start_reference)])
        if args.mode == "flow":
            from san_astra.control import Controller
            controller = Controller(pid=target_pid, ini_path=profile / "inis/PCSX2.ini")
            candidates = [w for w in controller.call("windows").get("windows", [])
                          if "grand theft auto" in w.get("title", "").lower()]
            if len(candidates) != 1:
                raise RuntimeError("Flow demo needs exactly one game window for wall-clock recording")
            screen_log = (directory / "screen-capture.log").open("x")
            screen_process = subprocess.Popen(["screencapture", "-v", f"-l{candidates[0]['id']}",
                "-x", str(screen_movie)], stdout=screen_log, stderr=subprocess.STDOUT, start_new_session=True)
            time.sleep(0.5)
            if screen_process.poll() is not None:
                raise RuntimeError("Wall-clock recording did not start; see screen-capture.log")
            manifest.update(wall_clock_master=str(screen_movie), screen_recorder_pid=screen_process.pid,
                clip_seconds_limit=None,
                duration_note="Full window recording preserves real elapsed time: 100% during actions and 50% during inference. Native GS capture separately preserves all emulator frames; its fixed-rate playback does not preserve slow motion.")
            write_json(manifest_path, manifest)
        manifest["driver_exit_code"] = drive(command, directory / "driver.stdout", environment)
        summary_path = directory / "run_summary.json"
        if summary_path.is_file():
            manifest["driver_summary"] = json.loads(summary_path.read_text())
        if manifest["driver_exit_code"]:
            failure = f"Autonomous driver exited {manifest['driver_exit_code']}; see driver.stdout"
    except BaseException as exc:
        failure = str(exc) or type(exc).__name__
    finally:
        if screen_process is not None:
            try:
                if screen_process.poll() is None:
                    screen_process.send_signal(signal.SIGINT)
                screen_process.wait(timeout=15)
                if screen_process.returncode != 0 or not screen_movie.is_file() or screen_movie.stat().st_size == 0:
                    raise RuntimeError("Wall-clock recording failed to finalize")
            except BaseException as exc:
                failure = failure or str(exc)
            finally:
                if screen_log is not None:
                    screen_log.close()
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
            replay = directory / ("recording/wall-clock.mp4" if args.mode == "flow" else "recording/first-minute.mp4")
            replay_source = screen_movie if args.mode == "flow" else playback
            clip_limit = [] if args.mode == "flow" else ["-t", "60"]
            video_filter = (r"scale=trunc(min(1024\,iw)/2)*2:-2,fps=30" if args.mode == "flow"
                            else "scale=trunc(iw/2)*2:trunc(ih/2)*2")
            clip = subprocess.run([recording.ffmpeg_path(), "-hide_banner", "-nostdin", "-n", "-i", str(replay_source),
                                   "-map", "0:v:0", *clip_limit, "-vf", video_filter, "-c:v", "libx264", "-preset", "fast",
                                   "-crf", "22" if args.mode == "flow" else "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
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
                            recorded_target_reached=exported["decoded_frame_count"] >= args.target_recorded_frames,
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
    parser.add_argument("--steps", type=int, default=120, help="Decision safety cap; duration is controlled by --target-recorded-frames")
    parser.add_argument("--frame-stride", type=int, default=60, help="Requested VSyncs per decision, 1..120 (default: 60)")
    parser.add_argument("--mode", choices=("stepped", "burst", "flow"), default="stepped", help="stepped frames, paused burst decisions, or flow with half-speed inference")
    parser.add_argument("--vision-max-edge", type=int, default=512)
    parser.add_argument("--bridge-transport", choices=("cli", "daemon"), default="daemon")
    parser.add_argument("--resume-from", type=Path, help="Continue visual context only; never replay controls")
    parser.add_argument("--start-reference", type=Path, help="Optional original starting screenshot; inherited from the resume manifest and fixed for this attempt")
    parser.add_argument("--target-recorded-frames", type=int, default=3597, help="Stored-frame target (3597 about one minute; 7193 about two minutes)")
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
