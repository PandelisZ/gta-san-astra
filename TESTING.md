# Live validation

Validated on this Mac with PCSX2 2.8.2, September 8, 2026.

- Native bridge compiles with the installed Swift toolchain.
- Accessibility and screen recording permissions are available.
- ScreenCaptureKit captures the actual PCSX2 window. The default 32-pixel titlebar crop produces game-only images; use `--crop-top 0` for fullscreen.
- Frame stepping advanced the PS2 BIOS from a paused black screen through its boot animation. Each returned screenshot showed paused emulation.
- The configured Cross input was exercised in the BIOS language screen alongside frame stepping.
- CLI returns screenshot files and writes action/observation JSONL records.
- MCP stdio initialization, tool listing, and `doctor` call pass against a real subprocess. Image response shape is covered in the test suite.
- Real MCP `observe` returned a decodable 489×480 PNG with the 32-pixel titlebar removed. Evidence: `runs/mcp-smoke/result.json`.
- Live stride checks sent 1, 5, and 10 VSync requests and returned screenshots. Two separate observations taken while paused had identical pixel hashes. Evidence: `runs/stride-smoke/result.json`.
- Live Astra image inference succeeded using the bundled Codex CLI, `gpt-6-astra`, with a structured decision in 7.36 seconds. Evidence is in `runs/vision-smoke/`.
- The older system Codex CLI rejected Astra. The runner now selects the newer app-bundled CLI; `SAN_ASTRA_CODEX` overrides this.
- A three-decision Astra loop operated the BIOS preferences menus from screenshots, including language confirmation. Evidence: `runs/bios-control/`.

## Remaining gameplay gate

The San Andreas image is still downloading at this checkpoint. Full GTA boot, vehicle control, and autonomous driving validation will be recorded here after the image is ready. BIOS control and a vision smoke test do not establish driving performance.

## Reproduce

```sh
uv run --extra test pytest
python3 native/smoke.py
uv run san-astra doctor
uv run san-astra --frame-stride 5 step
uv run python scripts/autodrive.py --steps 20 --frame-stride 10
uv run python scripts/report.py runs/<autodrive-run>
```

For experiments, start from the same saved driving scene and use a fixed stride. Review screenshots for actual behavior; requested VSync counts are not independent frame-delivery measurements.
