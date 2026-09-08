#!/usr/bin/env python3
"""Bounded screenshot-only driving through the user's authenticated Codex CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from statistics import median
import time
from typing import Callable

SCHEMA = Path(__file__).with_name("decision.schema.json")
BUTTONS = frozenset(json.loads(SCHEMA.read_text())["properties"]["buttons"]["items"]["enum"])
# Valid flags discovered using this machine's `codex features list`.
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "plugins", "remote_plugin", "browser_use",
    "browser_use_external", "computer_use", "in_app_browser", "image_generation",
    "multi_agent", "multi_agent_v2", "memories", "hooks", "skill_search",
    "code_mode_host", "code_mode", "workspace_dependencies", "goals", "tool_suggest",
)


def validate_decision(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"buttons", "rationale", "scene", "stop"}:
        raise ValueError("Decision must contain exactly buttons, rationale, scene, stop")
    buttons = value["buttons"]
    if not isinstance(buttons, list) or any(not isinstance(b, str) or b not in BUTTONS for b in buttons):
        raise ValueError("Decision contains invalid buttons")
    if len(buttons) != len(set(buttons)):
        raise ValueError("Decision contains duplicate buttons")
    if {"steer_left", "steer_right"} <= set(buttons):
        raise ValueError("Decision cannot steer both directions")
    if not isinstance(value["rationale"], str) or not 1 <= len(value["rationale"].strip()) <= 800:
        raise ValueError("Decision needs a concise rationale")
    if value["scene"] not in ("driving", "menu", "on_foot", "uncertain"):
        raise ValueError("Decision scene is invalid")
    if type(value["stop"]) is not bool:
        raise ValueError("Decision stop must be boolean")
    return value


def build_command(model: str, images: list[Path], output: Path, cwd: Path) -> list[str]:
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
    executable = os.environ.get("SAN_ASTRA_CODEX") or (str(bundled) if bundled.exists() else "codex")
    command = [executable, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
               "--enable", "skip_host_skill_discovery",
               "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--color", "never",
               "-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0",
               "--output-schema", str(SCHEMA.resolve()), "--output-last-message", str(output.resolve()),
               "--cd", str(cwd.resolve()), "-m", model]
    for feature in DISABLED_FEATURES:
        command.extend(["--disable", feature])
    for image in images[-2:]:
        command.extend(["--image", str(image.resolve())])
    return command + ["-"]


def make_prompt(goal: str, history: list[dict], image_count: int) -> str:
    return (
        "You are Astra driving GTA San Andreas in a PS2 emulator for a visual autonomy evaluation. "
        "Use ONLY the attached game screenshots and your own prior actions below. Do not call tools, "
        "inspect files, search the web, or obtain game telemetry. Return the required JSON decision. "
        f"There are {image_count} screenshots, oldest first; the final one is current. "
        "The emulator is paused while you decide. Each frame is one emulated VSync (approximately "
        "1/60 second for NTSC), not necessarily a distinct rendered game frame. "
        "Controls: cross accelerates; square brakes/reverses; steer_left/steer_right steer; r1 is "
        "handbrake; move_forward/move_backward move on foot; triangle enters/exits a vehicle; start pauses the game; d-pad navigates menus; "
        "cross confirms. Empty buttons coasts. The caller controls the fixed frame stride. Stay on roads, "
        "avoid collisions and pedestrians, and drive conservatively. Do not use cheat sequences. "
        "If the view is ambiguous, use a brief observation action or stop. Set stop=true when the "
        "goal is achieved or safe progress is impossible; no buttons are applied on a stop decision. "
        "Rationale must be a short visible-scene explanation, not hidden reasoning.\n"
        f"Goal: {goal}\nOwn previous decisions: {json.dumps(history[-12:])}\n"
    )


def decide(model: str, images: list[Path], history: list[dict], goal: str,
           directory: Path, index: int, timeout: float, runner: Callable = subprocess.run) -> tuple[dict, float]:
    output = directory / f"decision-{index:04d}.json"
    output.unlink(missing_ok=True)  # A failed run must never reuse a prior decision.
    # No project instructions or unrelated files in the model's working directory.
    model_cwd = directory / "model-workspace"
    model_cwd.mkdir(exist_ok=True)
    started = time.monotonic()
    try:
        result = runner(build_command(model, images, output, model_cwd),
                        input=make_prompt(goal, history, min(2, len(images))),
                        text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        for name, content in (("stdout", exc.stdout), ("stderr", exc.stderr)):
            (directory / f"codex-{index:04d}.{name}").write_text(
                content.decode(errors="replace") if isinstance(content, bytes) else content or "")
        raise RuntimeError(f"Codex decision timed out after {timeout} seconds") from exc
    latency = round((time.monotonic() - started) * 1000, 2)
    (directory / f"codex-{index:04d}.stdout").write_text(result.stdout)
    (directory / f"codex-{index:04d}.stderr").write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f"Codex exited {result.returncode}; inspect codex-{index:04d}.stderr")
    if not output.is_file():
        raise ValueError("Codex did not create a decision file")
    return validate_decision(json.loads(output.read_text())), latency


def run(controller, *, steps: int, goal: str, model: str, directory: Path,
        timeout: float = 120, frame_stride: int = 5, emulator_fps: float = 59.94,
        decision_fn: Callable = decide, scenario_state: str | None = None) -> list[dict]:
    if type(frame_stride) is not int or not 1 <= frame_stride <= 120:
        raise ValueError("frame_stride must be an integer between 1 and 120")
    if not 0 < emulator_fps < float("inf"):
        raise ValueError("emulator_fps must be finite and positive")
    directory.mkdir(parents=True, exist_ok=True)
    started_at, started_clock = time.time(), time.monotonic()
    manifest = {"model": model, "goal": goal, "frame_stride": frame_stride,
                "emulator_fps": emulator_fps, "steps_limit": steps, "scenario_state": scenario_state,
                "scenario_state_note": "Provenance label only; runner does not load this state",
                "started_at": started_at, "status": "running"}
    (directory / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    outcome, error, release_error = "completed", None, None
    actions_requested, actions_completed = 0, 0
    latencies = []
    history: list[dict] = []
    images: list[Path] = []
    log = directory / "decisions.jsonl"
    def record(event):
        with log.open("a") as handle:
            handle.write(json.dumps(event) + "\n")
    try:
        images.append(Path(controller.observe()["image_path"]))
        for index in range(steps):
            decision, latency = decision_fn(model, images[-2:], history,
                goal + f" Each action lasts {frame_stride} VSyncs ({frame_stride / emulator_fps:.3f} game seconds).",
                directory, index, timeout)
            validate_decision(decision)  # Validate even when a custom decision function is supplied.
            event = {"step": index, "timestamp": time.time(), "decision": decision,
                     "decision_latency_ms": latency, "frame_stride": frame_stride,
                     "nominal_observations_per_game_second": emulator_fps / frame_stride, "images": [str(p) for p in images[-2:]]}
            record(event)
            print(json.dumps(event), flush=True)
            history.append(decision)
            latencies.append(latency)
            if decision["stop"]:
                outcome = "stopped"
                break
            actions_requested += 1
            result = controller.step(buttons=decision["buttons"], frames=frame_stride)
            actions_completed += 1
            images.append(Path(result["observation"]["image_path"]))
            images = images[-2:]
    except BaseException as exc:
        outcome, error = "error", str(exc)
        record({"type": "error", "timestamp": time.time(), "error": error})
        raise
    finally:
        try:
            controller.release()
        except BaseException as exc:
            release_error = exc
            outcome = "error"
            record({"type": "release_error", "timestamp": time.time(), "error": str(exc)})
        summary = {**manifest, "status": outcome, "ended_at": time.time(),
                   "elapsed_wall_seconds": round(time.monotonic() - started_clock, 3),
                   "decision_count": len(history), "action_count": actions_completed,
                   "actions_requested": actions_requested,
                   "game_frames_requested": actions_requested * frame_stride,
                   "frames_in_completed_actions": actions_completed * frame_stride,
                   "frames_note": "Requested VSync counts, not independent game-state measurements",
                   "decision_latency_median_ms": median(latencies) if latencies else None,
                   "error": error or (str(release_error) if release_error is not None else None),
                   "release_error": str(release_error) if release_error is not None else None}
        (directory / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (directory / "run_manifest.json").write_text(json.dumps({**manifest, "status": outcome,
                                                               "ended_at": summary["ended_at"]}, indent=2) + "\n")
        if release_error is not None and error is None:
            raise release_error
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--goal", default="Drive safely along the road, avoiding collisions.")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--run-dir", type=Path, default=Path("runs") / time.strftime("autodrive-%Y%m%d-%H%M%S"))
    parser.add_argument("--scenario-state", help="Optional state path provenance label; does not load a save state")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--frame-stride", type=int, default=5, help="Observe every N emulated VSyncs (1..120); game pauses during model latency")
    parser.add_argument("--emulator-fps", type=float, default=59.94, help="Nominal VSync rate, for logging game-time observation cadence")
    args = parser.parse_args()
    if not 1 <= args.steps <= 10000 or args.timeout <= 0 or not 1 <= args.frame_stride <= 120 or not 0 < args.emulator_fps < float("inf"):
        parser.error("steps must be 1..10000, stride 1..120, timeout and emulator-fps positive")
    from san_astra.control import Controller
    run(Controller(run_dir=args.run_dir), steps=args.steps, goal=args.goal, model=args.model,
        directory=args.run_dir.resolve(), timeout=args.timeout, frame_stride=args.frame_stride,
        emulator_fps=args.emulator_fps, scenario_state=args.scenario_state)


if __name__ == "__main__":
    main()
