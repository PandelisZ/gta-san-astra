# Warm native RPC prototype

Build `sh native/build-daemon.sh`; launch `native/astra-daemon` as a persistent
child process. This builds a separate executable and does not replace the live
`astra-bridge` CLI. The daemon initializes AppKit once. With multiple emulator instances, provide
`pid` on every request; an omitted PID fails when selection is ambiguous.

Send one JSON object per stdin line and read one JSON object per stdout line.
Keep stdin open until responses have arrived. There is no startup banner.
Responses preserve `id` and add `request_elapsed_ms`; errors return `ok:false`
without ending the session. Unknown fields and malformed numeric fields fail.

```json
{"id":1,"op":"status"}
{"id":2,"op":"capture","output":"/tmp/frame.png","crop_top":32}
{"id":3,"op":"input","keys":["k"],"duration_ms":150,"focus":true}
{"id":4,"op":"step","keys":["k","a"],"frames":5,"frame_interval_ms":90}
{"id":5,"op":"release"}
```

Operations: `status`, `windows`, `focus`, `capture`, `input`, `step`, `release`.
Optional fields map to CLI options: `pid`, `window_id`, `output`, `crop_top`,
`keys` (array or comma-separated string), `duration_ms`, `frames`, `frame_key`,
`frame_interval_ms`, and `focus`. Key/frame/duration limits match the CLI.
`input` focuses by default; pass `focus:false` to suppress it. `step` focuses.
An already-active emulator skips the focus call and its delay.

Requests run sequentially, including timed holds. Inputs release at each action's
end, so this prototype does not retain throttle during model inference. Capture
requests wait for a preceding timed action. ScreenCaptureKit runs in the adjacent
short-lived `astra-bridge` helper under `~/.san-astra/capture.lock`, so several
warm daemons do not keep conflicting replayd sessions alive. The lock covers the
helper lifetime; the helper is terminated after five seconds or daemon shutdown. A received `release` interrupts active
keys immediately, although its response may wait for the current action's sleep
to finish. EOF, SIGINT, and SIGTERM release active keys and exit. EOF discards
pending requests, so piping JSON through a command that immediately closes stdin
is not a supported request/response pattern. SIGKILL cannot run cleanup.

The daemon controls only PCSX2. It does not acquire the Python controller's global
file lock; callers must keep using that lock and coordinate a single driver.
Only screenshot pixels and window metadata are read. No telemetry API is used.

`python3 native/daemon-smoke.py` checks the protocol, validation, screenshots, EOF,
and signals without sending game controls. Actual game-control verification must
be performed by the single operator who owns the active driving session.

The first single-daemon read-only test on September 8 measured status responses at
8–9 ms and two warm captures at 74–77 ms. That original in-process capture design
failed when several persistent daemons connected to replayd. The serialized helper
fix passed four concurrent clients with eight captures at 227–935 ms including
queueing. These are individual samples, not throughput guarantees. Native action
verification is separate from this read-only capture test.

Reproduce the multi-process regression without game inputs:

```
python3 native/daemon-multiprocess-smoke.py --pids PID1 PID2 PID3 PID4
```
