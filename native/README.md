# Astra macOS bridge

Requires macOS 14+, Swift compiler (Xcode Command Line Tools), and running PCSX2.
Build with `./native/build.sh`. Screen Recording and Accessibility permissions must
be granted to the launching application (e.g. Codex or terminal).

Every command emits one JSON object. Errors emit `{"ok":false,"error":"..."}` and
exit 1. An explicit `--pid PID` can select an emulator process.

```
native/astra-bridge status
native/astra-bridge windows
native/astra-bridge focus
native/astra-bridge capture --output /absolute/frame.png [--window-id 123] [--crop-top 32]
native/astra-bridge input --keys w,a --duration-ms 100 [--focus]
native/astra-bridge step --keys w --frames 10 --frame-key n --frame-interval-ms 35
native/astra-bridge step --keys '' --frames 1
native/astra-bridge release [--keys w,a,s,d]
```

Capture selects the largest visible layer-zero PCSX2 window unless given a window
ID. It captures only the selected window via ScreenCaptureKit, including when other
windows obscure it. It writes PNG and returns dimensions, window ID/title, and UTC
timestamp. Optional `--crop-top N` removes N pixels from the top (for window
chrome); zero is the default, and no title-bar size is assumed. No game state, memory, OCR, or telemetry is read.

Input sends CGEvents specifically to the emulator PID. Timed input is limited to
0–10000 ms; `step` focuses PCSX2 and advances 1–120 paused frames by pressing and
releasing the configured frame advance key. Each frame key press lasts 5 ms,
followed by the requested 10–1000 ms interval (default 35). This needs PCSX2's
FrameAdvance hotkey configured to N (or the supplied key), with gameplay paused
before starting. The returned `frames` count means frame-advance requests sent,
not independently measured rendered frames. `durationMs` and
`requestedDurationMs` report the requested input budget; `elapsedMs` measures
actual monotonic time from the first control event through final key release,
excluding app-focus delay. The bridge does not infer whether the emulator is paused or
whether a requested frame has rendered; the caller must verify the images.

Key names: lowercase letters, digits, arrows (`up`, `down`, `left`, `right`),
`space`, `enter`, `escape`, `tab`, `shift`, `ctrl`, `alt`, `command`, F1–F20, common
punctuation names, and `numpad0`–`numpad9`. See `keyMap` in main.swift for aliases.
Input and step may have empty keys to coast without gamepad input.

All held keys release on completion, error, SIGINT, or SIGTERM. SIGKILL/process
crashes cannot run cleanup; use `release` to send key-up for the configured game-control keys. Its default
list excludes frame/pause/save/load hotkeys, since PCSX2 can trigger hotkeys on
key release. Supply `--keys` for other explicitly known held keys. Normal cleanup
tracks active keydowns and never releases an already-released frame key.
No persistent input state is retained between invocations. The bridge never
changes PCSX2 settings.

Run `python3 native/smoke.py` with PCSX2 running to exercise validation, capture,
optional crop, neutral waits, and signal termination. It sends no game keys or
frame advances and stores screenshots only in a temporary directory.
