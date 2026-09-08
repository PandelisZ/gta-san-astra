#!/usr/bin/env python3
"""Bounded screenshot-only driving through the user's authenticated Codex CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from statistics import median
from functools import partial
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
    required = {"buttons", "rationale", "scene", "stop"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"segments", "route_note"}:
        raise ValueError("Decision needs buttons, rationale, scene, stop, and optional segments/route_note")
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
    if "route_note" in value and (not isinstance(value["route_note"], str) or not 1 <= len(value["route_note"].strip()) <= 400):
        raise ValueError("route_note must be a short nonempty string of at most 400 characters")
    segments = value.get("segments")
    if segments is not None:
        if not isinstance(segments, list) or not 1 <= len(segments) <= 6:
            raise ValueError("segments must be null or contain 1..6 control phases")
        for segment in segments:
            if not isinstance(segment, dict) or set(segment) != {"buttons", "frames"}:
                raise ValueError("Each segment needs exactly buttons and frames")
            if type(segment["frames"]) is not int or not 1 <= segment["frames"] <= 120:
                raise ValueError("Segment frames must be an integer from 1 to 120")
            validate_decision({"buttons": segment["buttons"], "rationale": "segment", "scene": value["scene"], "stop": False})
            if {"cross", "square"} <= set(segment["buttons"]):
                raise ValueError("A segment cannot accelerate and brake simultaneously")
    return value


def action_plan(decision: dict, frame_stride: int, steer_pulse_frames: int = 12) -> list[dict]:
    """Compile explicit phases, or retain legacy four-field decision behavior."""
    if decision["stop"]:
        return []
    if decision.get("segments") is not None:
        if sum(segment["frames"] for segment in decision["segments"]) != frame_stride:
            raise ValueError(f"Segment frame counts must sum to the fixed burst of {frame_stride}")
        return [{"buttons": list(segment["buttons"]), "frames": segment["frames"]} for segment in decision["segments"]]
    buttons = list(decision["buttons"])
    pulse = min(steer_pulse_frames, frame_stride)
    if decision["scene"] == "driving" and 0 < pulse < frame_stride and any(b in buttons for b in ("steer_left", "steer_right")):
        return [{"buttons": buttons, "frames": pulse},
                {"buttons": [b for b in buttons if b not in ("steer_left", "steer_right")], "frames": frame_stride - pulse}]
    return [{"buttons": buttons, "frames": frame_stride}]


def load_resume(directory: Path) -> tuple[list[dict], Path | None]:
    """Read prior visual decisions and one frame; never replay controls or load state."""
    directory = Path(directory).expanduser().resolve()
    log = directory / "decisions.jsonl"
    if not log.is_file():
        raise ValueError(f"Resume decision log does not exist: {log}")
    history, last_frame = [], None
    for number, line in enumerate(log.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Resume log has incomplete JSON on line {number}; finish the prior run first") from exc
        if event.get("type") == "resume_context":
            history.extend(validate_decision(decision) for decision in event.get("decisions", []))
        if "decision" in event:
            history.append(validate_decision(event["decision"]))
        if event.get("type") == "model_frame" and event.get("source_image_path"):
            candidate = Path(event["source_image_path"])
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            if candidate.is_file():
                last_frame = candidate.resolve()
    if not history:
        raise ValueError("Resume run contains no prior decisions")
    return history, last_frame


def build_command(model: str, images: list[Path], output: Path, cwd: Path, *,
                  reasoning_effort: str = "low", service_tier: str = "fast") -> list[str]:
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
    executable = os.environ.get("SAN_ASTRA_CODEX") or (str(bundled) if bundled.exists() else "codex")
    command = [executable, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
               "--enable", "skip_host_skill_discovery",
               "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--color", "never",
               "-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0",
               "-c", "model_reasoning_effort=" + json.dumps(reasoning_effort),
               "-c", "service_tier=" + json.dumps(service_tier),
               "--output-schema", str(SCHEMA.resolve()), "--output-last-message", str(output.resolve()),
               "--cd", str(cwd.resolve()), "-m", model]
    for feature in DISABLED_FEATURES:
        command.extend(["--disable", feature])
    for image in images[-2:]:
        command.extend(["--image", str(image.resolve())])
    return command + ["-"]


def make_prompt(goal: str, history: list[dict], image_count: int, mode: str = "stepped") -> str:
    timing = ("The emulator is paused while you decide. Each frame is one emulated VSync "
              "(approximately 1/60 second for NTSC), not necessarily a distinct rendered game frame. "
              if mode == "stepped" else
              "The emulator runs continuously, including while you decide. Your screenshot becomes older "
              "during inference. Controls are held briefly, then released, and the vehicle coasts during inference. "
              "Do not assume the world stopped at the screenshot. Favor simple conservative controls. ")
    route_note = next((decision["route_note"] for decision in reversed(history) if decision.get("route_note")),
                      "No prior route state: identify visible starting landmarks and intended first turn.")
    return (
        "You are Astra driving GTA San Andreas in a PS2 emulator for a visual autonomy evaluation. "
        "Use ONLY the attached game screenshots and your own prior actions below. Do not call tools, "
        "inspect files, search the web, or obtain game telemetry. Return the required JSON decision. "
        f"There are {image_count} screenshots, oldest first; the final one is current. "
        + timing +
        "Controls: cross accelerates; square brakes/reverses; steer_left/steer_right steer; r1 is "
        "handbrake; move_forward/move_backward move on foot; triangle enters/exits a vehicle; start pauses the game; d-pad navigates menus; "
        "cross confirms. Empty buttons coasts. The caller controls the total action duration. "
        "In stepped mode, choose segments: 1..6 sequential {buttons,frames} phases whose frame counts "
        "sum exactly to the requested burst. Each phase releases the prior phase's controls. Set top-level "
        "buttons to the first phase's buttons. You choose each throttle, brake and steering duration. "
        "A gentle correction may need 4..12 steering frames; an actual corner may need 25..60 frames "
        "at low speed. Do not blindly reuse the short correction duration for a right-angle turn. "
        "Square first brakes forward motion, then reverses after stopping; a brief pulse may only brake "
        "and create almost no backward travel. Distinguish slowing from intentional reversing. "
        "For reversing, choose duration from the movement actually observed after your previous pulse, "
        "not a fixed short-pulse limit. Never hold cross and square together. "
        "For right corners, first advance far enough that the front can arc around the near curb "
        "into the destination roadway; do not aim through the inside sidewalk or pole. Use the visible "
        "curb opening and vehicle's front corners to judge clearance. Ease steering as the car aligns "
        "with the destination road rather than repeating a tight turn into its inside curb. "
        "Example 60-frame burst: square for8, coast for12, cross+steer_left for40. "
        "Use segments=null in realtime mode, or for a stop decision. "
        "For menu confirmations/one-shot actions, follow a press with one empty-buttons decision so "
        "the game samples release before pressing the same button again. Driving continuous held "
        "controls do not need neutral gaps. Host key release between paused steps is only sampled "
        "when the next emulated frame advances. Stay on roads, "
        "avoid collisions and pedestrians, and drive conservatively. Do not use cheat sequences. "
        "If the view is ambiguous, choose low-motion/coasting phases and inspect the next view. "
        "If commanded motion produces little visible displacement across two observations, diagnose "
        "the blockage and change the plan instead of repeating it indefinitely. If a short reverse "
        "barely moved the car and the rearward path remains clear, increase the next reverse phase "
        "meaningfully within the fixed burst instead of repeating the same ineffective pulse. "
        "An intentional reverse may use most or all of the burst when visible clearance supports it; "
        "shorten it when pedestrians or traffic constrain the path. Compare displacement against "
        "fixed poles and curb edges, not camera rotation alone. Before changing back to forward drive, "
        "confirm the front corner has cleared the obstruction; the rear reaching the roadway is not "
        "enough. Preserve the last attempted duration, observed effect and next adjustment in route_note. "
        "Learn steering and throttle strength from your own observed displacement. Wait for traffic "
        "when necessary, but use a visibly clear route "
        "when one opens. Set stop=true only when the route goal is visibly complete or the situation "
        "is truly unrecoverable; ordinary uncertainty or traffic is not completion. No buttons are "
        "applied on a stop decision. "
        "Update route_note in at most400characters: starting landmark, current leg, visually completed "
        "turn count, next turn/landmark, and observed steering/braking response. Carry forward still-relevant "
        "facts from the previous note. Count a completed turn only after the images show it happened, "
        "never because a turn was commanded. Mark uncertain facts uncertain. For an around-the-block goal, "
        "success requires visibly returning to the starting landmark/road orientation; turn count alone "
        "does not prove completion. This note is your own visual navigation memory, never telemetry. "
        "Rationale must be a short visible-scene explanation, not hidden reasoning.\n"
        f"Goal: {goal}\nPrevious visual route note: {route_note}\nOwn previous decisions: {json.dumps(history[-5:])}\n"
    )


def decide(model: str, images: list[Path], history: list[dict], goal: str,
           directory: Path, index: int, timeout: float, runner: Callable = subprocess.run, *,
           reasoning_effort: str = "low", service_tier: str = "fast", mode: str = "stepped") -> tuple[dict, float]:
    output = directory / f"decision-{index:04d}.json"
    output.unlink(missing_ok=True)  # A failed run must never reuse a prior decision.
    # No project instructions or unrelated files in the model's working directory.
    model_cwd = directory / "model-workspace"
    model_cwd.mkdir(exist_ok=True)
    started = time.monotonic()
    try:
        result = runner(build_command(model, images, output, model_cwd,
                                      reasoning_effort=reasoning_effort, service_tier=service_tier),
                        input=make_prompt(goal, history, min(2, len(images)), mode),
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
        timeout: float = 120, frame_stride: int = 60, emulator_fps: float = 59.94,
        decision_fn: Callable = decide, scenario_state: str | None = None,
        reasoning_effort: str = "low", service_tier: str = "fast",
        mode: str = "stepped", hold_ms: int = 150, vision_max_edge: int | None = None,
        vision_quality: int = 65, vision_colormode: str = "rgb",
        policy_transport: str = "cli", bridge_transport: str = "cli",
        steer_pulse_frames: int = 12, resume_from: Path | None = None,
        recording_master: Path | None = None, target_recorded_frames: int | None = None) -> list[dict]:
    if type(frame_stride) is not int or not 1 <= frame_stride <= 120:
        raise ValueError("frame_stride must be an integer between 1 and 120")
    if type(steer_pulse_frames) is not int or not 0 <= steer_pulse_frames <= 120:
        raise ValueError("steer_pulse_frames must be an integer between 0 and 120")
    if not 0 < emulator_fps < float("inf"):
        raise ValueError("emulator_fps must be finite and positive")
    if mode not in ("stepped", "realtime") or type(hold_ms) is not int or not 50 <= hold_ms <= 2000:
        raise ValueError("mode must be stepped or realtime; hold_ms must be 50..2000")
    if (recording_master is None) != (target_recorded_frames is None):
        raise ValueError("recording_master and target_recorded_frames must be provided together")
    if target_recorded_frames is not None and (type(target_recorded_frames) is not int or target_recorded_frames < 1 or mode != "stepped"):
        raise ValueError("Recorded-frame target must be positive and use stepped mode")
    if decision_fn is decide:
        decision_fn = partial(decide, reasoning_effort=reasoning_effort, service_tier=service_tier, mode=mode)
    resume_history, resume_image = [], None
    if resume_from is not None:
        resume_from = Path(resume_from).expanduser().resolve()
        if directory.resolve() == resume_from:
            raise ValueError("Continuation needs a NEW --run-dir, different from --resume-from")
        if (directory / "decisions.jsonl").exists():
            raise ValueError("Continuation output already contains decisions; choose a new --run-dir")
        resume_history, resume_image = load_resume(resume_from)
    directory.mkdir(parents=True, exist_ok=True)
    started_at, started_clock = time.time(), time.monotonic()
    manifest = {"model": model, "reasoning_effort": reasoning_effort, "service_tier": service_tier, "goal": goal, "frame_stride": frame_stride,
                "emulator_fps": emulator_fps, "steer_pulse_frames": steer_pulse_frames,
                "control_plan": "model-selected sequential segments; legacy decisions use steering pulse fallback",
                "steps_limit": steps, "scenario_state": scenario_state,
                "scenario_state_note": "Provenance label only; runner does not load this state",
                "resume_from": str(resume_from) if resume_from else None,
                "resume_decision_count": len(resume_history),
                "resume_image_path": str(resume_image) if resume_image else None,
                "resume_note": "Visual context only; no actions replayed, no game state loaded or reset. Emulator must already be at the continuation position.",
                "recording_master": str(recording_master) if recording_master else None,
                "target_recorded_frames": target_recorded_frames,
                "recording_budget_note": "Live stored-frame count is a buffered lower bound. Final bursts are at least15 requests where possible; stopped recording can exceed the target.",
                "started_at": started_at, "status": "running", "mode": mode,
                "hold_ms": hold_ms if mode == "realtime" else None,
                "policy_transport": policy_transport, "bridge_transport": bridge_transport,
                "vision_max_edge": vision_max_edge, "vision_quality": vision_quality,
                "vision_colormode": vision_colormode}
    (directory / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    outcome, error, release_error = "completed", None, None
    actions_requested, actions_completed = 0, 0
    frames_requested, frames_completed = 0, 0
    recorded_frames = 0
    latencies = []
    history: list[dict] = list(resume_history)
    images: list[Path] = []
    raw_images: list[Path] = []
    prepared: list[dict] = []
    capture_latencies = []
    action_latencies = []
    log = directory / "decisions.jsonl"
    def record(event):
        with log.open("a") as handle:
            handle.write(json.dumps(event) + "\n")
    def add_observation(observation):
        raw = Path(observation["image_path"])
        raw_images.append(raw)
        if isinstance(observation.get("capture_ms"), (int, float)):
            capture_latencies.append(observation["capture_ms"])
        if vision_max_edge is not None:
            from san_astra.frames import prepare_frame
            metadata = prepare_frame(raw, directory / "model-frames", max_edge=vision_max_edge,
                                     quality=vision_quality, colormode=vision_colormode)
        else:
            metadata = {"source_image_path": str(raw), "image_path": str(raw), "processing_ms": 0}
        prepared.append(metadata)
        images.append(Path(metadata["image_path"]))
        del images[:-2], raw_images[:-2], prepared[:-2]
        record({"type": "model_frame", **metadata})
    try:
        if resume_history:
            record({"type": "resume_context", "resume_from": str(resume_from), "decisions": resume_history})
        if resume_image is not None:
            add_observation({"image_path": str(resume_image)})
        add_observation(controller.observe())
        if recording_master is not None:
            from recording import count_frames
            recorded_frames = count_frames(recording_master)
        for index in range(steps):
            if target_recorded_frames is not None and recorded_frames >= target_recorded_frames:
                outcome = "recording_target_reached"
                break
            current_stride = (min(frame_stride, max(min(15, frame_stride), target_recorded_frames - recorded_frames))
                              if target_recorded_frames is not None else frame_stride)
            decision, latency = decision_fn(model, images[-2:], history,
                goal + (f" Each action lasts exactly {current_stride} requested VSyncs ({current_stride / emulator_fps:.3f} nominal game seconds)."
                        " Select control segments whose frame counts sum exactly to that total. "
                        "Controls in each segment remain held for its chosen frames, including steering; "
                        "there is no automatic short steering cap on explicit segments. "
                        "Predict the vehicle path across the entire burst."
                        if mode == "stepped" else f" Each action holds for {hold_ms} milliseconds, then releases."),
                directory, index, timeout)
            validate_decision(decision)  # Validate even when a custom decision function is supplied.
            segments = []
            if not decision["stop"]:
                if mode == "stepped":
                    segments = action_plan(decision, current_stride, steer_pulse_frames)
                else:
                    segments = [{"buttons": list(decision["buttons"]), "duration_ms": hold_ms}]
            event = {"step": index, "timestamp": time.time(), "decision": decision,
                     "decision_latency_ms": latency, "frame_stride": current_stride,
                     "recorded_frames_before": recorded_frames if recording_master else None,
                     "nominal_observations_per_game_second": emulator_fps / current_stride if mode == "stepped" else None,
                     "mode": mode, "action_plan": segments, "images": [str(p) for p in raw_images[-2:]],
                     "model_images": [str(p) for p in images[-2:]], "model_frame_metadata": list(prepared)}
            record(event)
            print(json.dumps(event), flush=True)
            history.append(decision)
            latencies.append(latency)
            if decision["stop"]:
                outcome = "stopped"
                break
            actions_requested += 1
            action_started = time.monotonic()
            if mode == "stepped":
                for segment in segments:
                    frames_requested += segment["frames"]
                    result = controller.step(buttons=segment["buttons"], frames=segment["frames"])
                    frames_completed += segment["frames"]
            else:
                result = controller.action(buttons=decision["buttons"], duration_ms=hold_ms)
            action_latencies.append((time.monotonic() - action_started) * 1000)
            actions_completed += 1
            add_observation(result["observation"])
            if recording_master is not None:
                time.sleep(0.15)
                recorded_frames = max(recorded_frames, count_frames(recording_master))
                record({"type": "recording_progress", "step": index, "recorded_frames_lower_bound": recorded_frames,
                        "target_recorded_frames": target_recorded_frames, "requested_frames_so_far": frames_requested})
        if target_recorded_frames is not None and recorded_frames >= target_recorded_frames:
            outcome = "recording_target_reached"
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
                   "decision_count": len(history) - len(resume_history), "action_count": actions_completed,
                   "actions_requested": actions_requested,
                   "game_frames_requested": frames_requested if mode == "stepped" else None,
                   "frames_in_completed_actions": frames_completed if mode == "stepped" else None,
                   "recorded_frames_lower_bound": recorded_frames if recording_master else None,
                   "recording_target_reached": recorded_frames >= target_recorded_frames if target_recorded_frames else None,
                   "realtime_hold_ms_requested": actions_requested * hold_ms if mode == "realtime" else None,
                   "frames_note": "Requested VSync counts, not independent game-state measurements",
                   "decision_latency_median_ms": median(latencies) if latencies else None,
                   "capture_latency_median_ms": median(capture_latencies) if capture_latencies else None,
                   "action_and_capture_median_ms": median(action_latencies) if action_latencies else None,
                   "measured_decisions_per_wall_second": (len(history) - len(resume_history)) / max(time.monotonic() - started_clock, 0.001),
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
    parser.add_argument("--mode", choices=["stepped", "realtime"], default="stepped")
    parser.add_argument("--hold-ms", type=int, default=150, help="Realtime bounded input hold, followed by coasting during inference")
    parser.add_argument("--bridge-transport", choices=["cli", "daemon"], default="daemon")
    parser.add_argument("--policy-transport", choices=["cli", "app-server"], default="app-server")
    parser.add_argument("--vision-max-edge", type=int, default=512)
    parser.add_argument("--vision-quality", type=int, default=65)
    parser.add_argument("--vision-colormode", choices=["rgb", "gray", "contrast"], default="rgb")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--goal", default="Drive safely along the road, avoiding collisions.")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--reasoning-effort", default="low", help="Codex reasoning effort (default: low)")
    parser.add_argument("--service-tier", default="fast", help="Codex service tier (default: fast)")
    parser.add_argument("--run-dir", type=Path, default=Path("runs") / time.strftime("autodrive-%Y%m%d-%H%M%S"))
    parser.add_argument("--resume-from", type=Path, help="Carry prior decisions/visual route note and last frame into a NEW run; does not reset or load the game")
    parser.add_argument("--scenario-state", help="Optional state path provenance label; does not load a save state")
    parser.add_argument("--recording-master", type=Path, help="Live native MKV to count after each burst")
    parser.add_argument("--target-recorded-frames", type=int, help="Stop at this stored-frame lower bound, subject to --steps safety cap")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--frame-stride", type=int, default=60, help="Observe every N emulated VSyncs (1..120); game pauses during model latency")
    parser.add_argument("--steer-pulse-frames", type=int, default=12, help="Steering frames per driving burst; 0 holds steering for the full stride")
    parser.add_argument("--emulator-fps", type=float, default=59.94, help="Nominal VSync rate, for logging game-time observation cadence")
    args = parser.parse_args()
    if not 1 <= args.steps <= 10000 or args.timeout <= 0 or not 1 <= args.frame_stride <= 120 or not 0 < args.emulator_fps < float("inf"):
        parser.error("steps must be 1..10000, stride 1..120, timeout and emulator-fps positive")
    from contextlib import ExitStack
    from san_astra.control import Controller
    with ExitStack() as stack:
        if args.bridge_transport == "daemon":
            from san_astra.daemon import DaemonController
            controller = DaemonController(run_dir=args.run_dir)
            stack.callback(controller.close)
        else:
            controller = Controller(run_dir=args.run_dir)
        decision_fn = decide
        if args.policy_transport == "app-server":
            from san_astra.policy import CodexPolicy
            policy = stack.enter_context(CodexPolicy(model=args.model, directory=args.run_dir.resolve(),
                timeout=args.timeout, effort=args.reasoning_effort, service_tier=args.service_tier))
            def decision_fn(model, images, history, goal, directory, index, timeout):
                value, latency = policy.decide(images=images, prompt=make_prompt(goal, history, len(images), args.mode),
                                                output_schema=json.loads(SCHEMA.read_text()))
                (directory / f"decision-{index:04d}.json").write_text(json.dumps(value) + "\n")
                return validate_decision(value), latency
        run(controller, steps=args.steps, goal=args.goal, model=args.model,
            directory=args.run_dir.resolve(), timeout=args.timeout, frame_stride=args.frame_stride,
            emulator_fps=args.emulator_fps, scenario_state=args.scenario_state,
            reasoning_effort=args.reasoning_effort, service_tier=args.service_tier,
            mode=args.mode, hold_ms=args.hold_ms, vision_max_edge=args.vision_max_edge,
            vision_quality=args.vision_quality, vision_colormode=args.vision_colormode,
            policy_transport=args.policy_transport, bridge_transport=args.bridge_transport,
            decision_fn=decision_fn, steer_pulse_frames=args.steer_pulse_frames, resume_from=args.resume_from,
            recording_master=args.recording_master, target_recorded_frames=args.target_recorded_frames)



if __name__ == "__main__":
    main()
