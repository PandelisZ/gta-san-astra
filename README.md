# GTA San Astra

Visual autonomous driving in GTA San Andreas on PCSX2. Astra receives screenshots, chooses PS2 controls, and sees the resulting screenshot. No game memory, coordinates, speed telemetry, or emulator debug API is used.

The native macOS bridge injects keyboard events into PCSX2's configured DualShock 2 bindings. The game stays paused between decisions. A step holds controls, pulses PCSX2's Frame Advance hotkey, releases controls, and captures the emulator window.

## Quick start

Requires macOS 14+, Xcode Command Line Tools, `uv`, PCSX2, a configured PS2 BIOS, and your local San Andreas game image. The checked-in profile setup targets the PCSX2 2.8.2 app installed on this machine. No game or BIOS files are distributed.

```sh
sh scripts/bootstrap.sh
# Quit any existing PCSX2 instance first.
python3 scripts/setup_emulator.py --iso "/path/to/San Andreas.iso" --launch
uv run san-astra observe
uv run san-astra --frame-stride 5 step --throttle
```

The setup script creates an isolated profile under `.runtime/pcsx2`; the existing PCSX2 profile is preserved. It references the existing BIOS and creates separate memory cards/save states. It sets `StartPaused=true` and `FrameAdvance=Keyboard/N`. On macOS, PCSX2 appends `PCSX2` to the `-datapath` base directory.

If `doctor` reports missing permissions, enable the host terminal/Codex app under macOS Privacy & Security → Accessibility and Screen & System Audio Recording. The emulator window must be visible, not minimized.

## Choose which frames Astra sees

Use any stride from 1 to 120:

```sh
uv run san-astra --frame-stride 1 step --throttle  # every frame
uv run san-astra --frame-stride 5 step --throttle  # every fifth frame
uv run san-astra --frame-stride 10 step --throttle # every tenth frame
SAN_ASTRA_FRAME_STRIDE=10 uv run san-astra mcp
```

`step --frames N` overrides the default for one action. The autonomous runner uses a fixed `--frame-stride` throughout a run, so the model cannot silently change the experiment's cadence.

At NTSC 59.94 VSyncs/second, strides 1, 5, and 10 correspond nominally to 59.94, 11.99, and 5.99 observations per **game second**. These are not wall-clock FPS: the game pauses during model inference, and GTA may render repeated frames. The driver sends timed frame-advance requests; without reading emulator telemetry it cannot assert that every request became a unique rendered frame.

## Drive with Astra

The automated runner uses the existing authenticated Codex CLI with `gpt-6-astra`; it does not require a separate API key. It prefers the newer app-bundled CLI when available; set `SAN_ASTRA_CODEX` to choose another executable. Each decision receives the latest two screenshots and its own previous actions. Tools and web access are disabled for the decision process.

```sh
uv run python scripts/autodrive.py \
  --model gpt-6-astra --steps 20 --frame-stride 10 \
  --goal "Drive along the road, stay in the lane, and avoid collisions."
```

Start from a paused driving scene for a driving evaluation. Menus and opening cutscenes can also be traversed with the controls. The bounded runner stops after the requested number of decisions or when Astra chooses to stop. Ctrl-C releases game controls. It uses `--ignore-user-config` to avoid unrelated MCP servers, plugins, and local configuration incompatibilities; authentication is retained.

## CLI and MCP

```sh
uv run san-astra doctor
uv run san-astra observe
uv run san-astra step --frames 10 --throttle --steer left
uv run san-astra step --frames 5 --brake
uv run san-astra step --frames 5 --buttons triangle
uv run san-astra step --frames 5 --buttons start
uv run san-astra step --frames 10 --buttons move_forward
uv run san-astra release
```

For realtime input while the emulator is running, use `action --duration-ms 150 --throttle`. Unlike `step`, realtime actions allow the world to continue during inference. Space in the emulator toggles its pause state; Start is the game's own pause/menu button.

For repeated menu confirmations, insert an empty `step` between presses so the game can sample the released button. Consecutive driving steps can keep accelerating or steering. `--crop-top 32` removes the titlebar by default; use `--crop-top 0` for fullscreen, or set `SAN_ASTRA_CROP_TOP`.

`.codex/config.toml` registers this repository's MCP server for a new trusted Codex session. The current session can use the CLI immediately. MCP exposes `observe`, `step`, `action`, `release`, and `doctor`, with PNG image content returned inline by observation tools. Update the absolute paths if you move this checkout.

| Driving control | PS2 button | Current keyboard |
| --- | --- | --- |
| Accelerate | Cross | K |
| Brake / reverse | Square | J |
| Steer | Left stick | A / D |
| Enter / exit | Triangle | I |
| Handbrake | R1 | E |
| Game menu | Start | Return |
| Walk forward / back | Left stick | W / S |

The Python controller reads keyboard mappings from the isolated profile when present. Override with `SAN_ASTRA_PCSX2_INI`. Steering currently uses digital stick directions; finer steering comes from shorter holds, not an analog virtual gamepad.

## Evidence and evaluation

Each action and screenshot is saved beneath `runs/` with timestamps, requested frames, actual wall time, input buttons, and image paths. Autonomous runs also include validated model decisions, model latency, and the fixed stride. Keep a saved driving scenario for comparisons; PCSX2 supports launching it with `--statefile` through `setup_emulator.py`.

Autonomous runs write `run_manifest.json` and `run_summary.json` with the model, goal, stride, outcome, requested frame counts, and latency. `--scenario-state PATH` records the initial scenario's provenance; it does not load that state or expose it to the model. Generate a local screenshot gallery with:

```sh
uv run python scripts/report.py runs/<autodrive-run>
# Optional manual observations keyed by decision number:
uv run python scripts/report.py runs/<autodrive-run> --annotations ratings.json
```

Judge road following, visible collisions, pedestrian avoidance, recovery, and task completion from screenshots or a human review. Logs do not contain ground-truth collision counts or distances, and model self-reports are not objective scores. Save state resets are emulator controls only; the policy never receives save-state contents.

## Validation

```sh
uv run --extra test pytest
python3 native/smoke.py
```

The unit suite covers control bounds, locks, failure cleanup, stride configuration, MCP image responses, and decision validation. Native smoke checks require a running visible PCSX2 window. See `TESTING.md` for live evidence and any remaining gates.

Implementation references: [PCSX2 frame-advance hotkey](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/Hotkeys.cpp), [VM frame stepping](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/VMManager.cpp), [Codex noninteractive execution](https://developers.openai.com/codex/noninteractive/).
