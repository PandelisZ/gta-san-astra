#!/usr/bin/env python3
"""Closed neutral-pulse calibration. Run only after trials finish, paused, capture OFF.

Without --run, prints the experiment plan and sends no inputs. No driving keys are
accepted: only frame advance and the recording toggle are emitted. No reset/focus.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import recording
from san_astra.control import Controller
from san_astra.processes import verify_profile_pid


def foreground() -> dict:
    """Read LaunchServices foreground metadata; never activates an application."""
    try:
        asn = subprocess.run(['/usr/bin/lsappinfo', 'front'], capture_output=True,
                             text=True, timeout=3, check=True).stdout.strip()
        info = subprocess.run(['/usr/bin/lsappinfo', 'info', '-only', 'pid,bundleid,name', asn],
                              capture_output=True, text=True, timeout=3)
        return {'timestamp': time.time(), 'asn': asn, 'info': info.stdout.strip()}
    except Exception as exc:
        return {'timestamp': time.time(), 'unavailable': str(exc)}


def final_counts(master: Path, ffprobe: str | None) -> dict:
    if ffprobe:
        result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                                 '-count_frames', '-count_packets', '-show_entries',
                                 'stream=nb_read_frames,nb_read_packets,time_base,duration,width,height:format=duration',
                                 '-of', 'json', str(master)], capture_output=True, text=True,
                                check=True, timeout=30)
        details = json.loads(result.stdout)
        return {'method': 'ffprobe closed-file decode', 'details': details,
                'decoded_frames': int(details['streams'][0]['nb_read_frames'])}
    # Homebrew ffprobe currently cannot load libx265. Count both packets and
    # decoded frames using the working recording.ffmpeg_path() executable.
    result = subprocess.run([recording.ffmpeg_path(), '-hide_banner', '-nostdin',
                             '-threads', '1', '-i', str(master), '-map', '0:v:0',
                             '-fps_mode', 'passthrough', '-f', 'null', '-',
                             '-progress', 'pipe:1', '-nostats'], capture_output=True,
                            text=True, check=True, timeout=30)
    counts = [int(line.split('=', 1)[1]) for line in result.stdout.splitlines()
              if line.startswith('frame=')]
    return {'method': 'FFmpeg closed-file decode fallback; ffprobe unavailable',
            'decoded_frames': max(counts), 'packets': recording.count_frames(master)}


def experiment(args, label: str, ffprobe: str | None, helper: bool) -> dict:
    destination = args.output / label
    destination.mkdir()
    controller = Controller(pid=args.pid, ini_path=args.profile/'inis/PCSX2.ini',
                            run_dir=destination/'target-observations')
    video_dir = Path(recording.status(args.profile)['directory'])
    existing = set(video_dir.glob('*.mkv'))
    report = {'label': label, 'pid': args.pid, 'profile': str(args.profile),
              'requested_pulses': args.frames, 'frame_interval_ms': args.interval_ms,
              'driving_keys': [], 'helper_enabled': helper, 'helper_calls': [],
              'foreground_before': foreground(), 'started_at': time.time()}
    stop = threading.Event()
    worker = None
    capture_started = False
    master = None
    try:
        report['record_start'] = recording.toggle(args.profile, args.pid)
        capture_started = True
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            created = set(video_dir.glob('*.mkv')) - existing
            if len(created) == 1:
                master = created.pop()
                break
            if len(created) > 1:
                raise RuntimeError('More than one new capture appeared; isolation lost')
            time.sleep(.1)
        if master is None:
            raise RuntimeError('No new capture appeared; expected recording OFF before calibration')
        report['master'] = str(master)
        if helper:
            observer = Controller(pid=args.helper_pid, ini_path=args.helper_profile/'inis/PCSX2.ini',
                                  run_dir=destination/'helper-observations')
            def observe_loop():
                while not stop.wait(args.helper_every):
                    call = {'started_at': time.time()}
                    try:
                        result = observer.observe()
                        call['result'] = result
                    except Exception as exc:
                        call['error'] = str(exc)
                        stop.set()
                    call['finished_at'] = time.time()
                    report['helper_calls'].append(call)
            worker = threading.Thread(target=observe_loop, daemon=True)
            worker.start()
        report['pulse_started_at'] = time.time()
        with controller.lock():
            report['native'] = controller.call('step', '--keys', '', '--frames', str(args.frames),
                                                '--frame-key', 'n', '--frame-interval-ms', str(args.interval_ms))
        report['pulse_finished_at'] = time.time()
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        stop.set()
        if worker:
            worker.join(timeout=30)
            report['helper_thread_finished'] = not worker.is_alive()
        if capture_started:
            try:
                report['record_stop'] = recording.toggle(args.profile, args.pid)
            except Exception as exc:
                report['record_stop_error'] = str(exc)
        report['foreground_after'] = foreground()
        report['finished_at'] = time.time()
        (destination/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    if 'record_stop_error' in report:
        raise RuntimeError('Capture stop failed; do not treat this file as finalized')
    # Native stop flushes on the emulator; require stable bytes before decoding.
    previous = None
    stable = 0
    for _ in range(50):
        current = (master.stat().st_size, master.stat().st_mtime_ns)
        stable = stable + 1 if current == previous else 0
        if stable >= 3:
            break
        previous = current
        time.sleep(.1)
    else:
        raise RuntimeError('Capture file did not settle after stop')
    report['final_counts'] = final_counts(master, ffprobe)
    report['stored_minus_requested'] = report['final_counts']['decoded_frames'] - args.frames
    report['qualification'] = 'Closed recorded-frame count; not independent proof of simulator VSync count.'
    (destination/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid', type=int, required=True)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--interval-ms', type=int, default=90)
    p.add_argument('--frames', type=int, default=60)
    p.add_argument('--helper-pid', type=int)
    p.add_argument('--helper-profile', type=Path)
    p.add_argument('--helper-every', type=float, default=1.0)
    p.add_argument('--ffprobe')
    p.add_argument('--run', action='store_true', help='Execute only after target is paused with capture OFF and all trials finished')
    args = p.parse_args()
    if not (args.pid > 0 and 1 <= args.frames <= 120 and 10 <= args.interval_ms <= 1000 and args.helper_every >= .25):
        p.error('Invalid PID, pulse count, interval or helper cadence')
    if bool(args.helper_pid) != bool(args.helper_profile) or args.helper_pid == args.pid:
        p.error('Helper needs its own distinct PID and profile')
    args.profile = args.profile.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.helper_profile:
        args.helper_profile = args.helper_profile.expanduser().resolve()
    plan = {'pid': args.pid, 'profile': str(args.profile), 'frames_per_clip': args.frames,
            'interval_ms': args.interval_ms, 'clips': ['baseline'] + (['with-helper'] if args.helper_pid else []),
            'output': str(args.output), 'requires': 'All trials finished; target paused; recording OFF; exclusive target ownership.'}
    if not args.run:
        print(json.dumps(plan, indent=2))
        return
    if not any(args.output.is_relative_to(ROOT/name) for name in ('runs', '.runtime')):
        p.error('Output must be under root runs/ or .runtime/')
    verify_profile_pid(args.pid, args.profile)
    if args.helper_pid:
        verify_profile_pid(args.helper_pid, args.helper_profile)
    probe = args.ffprobe or shutil.which('ffprobe')
    if probe and subprocess.run([probe, '-version'], capture_output=True).returncode:
        if args.ffprobe:
            p.error('Explicit ffprobe executable failed')
        probe = None
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for label in plan['clips']:
        result = experiment(args, label, probe, label == 'with-helper')
        results.append(result)
        print(json.dumps({'label':label, 'final_counts':result['final_counts'], 'report':str(args.output/label/'report.json')}), flush=True)
        (args.output/'summary.json').write_text(json.dumps({'plan':plan, 'results':results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
