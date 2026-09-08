# Junction stream

## Minute 01 setup

- Isolated worktree: `/Users/pz/.codex/worktrees/9143/oaihackathon`.
- Emulator PID: `66528`; profile: `.runtime/stream-junction/pcsx2`.
- Shared harness baseline: `0ac5edd`; shared read-only scenario: `quiet-tahoma`.
- Preparation: load opaque baseline, then 60 neutral frame requests. Captured image shows the blue Tahoma at the left curb, garden wall left, orange motel right, clock 17:15.
- Policy remains screenshot-only `gpt-6-astra`, low reasoning, fast service, 640-pixel maximum edge. Every driving phase comes from the existing policy. Explicit PID/profile targeting and global focus mutex remain intact.
- General prompt change: identify near and far curbs and connecting asphalt; evaluate the whole vehicle's corner sweep rather than inferring clearance from a building gap, signal, or vehicle center.
- Attempt: `stream-junction-minute-01`; target 3,597 actual stored frames. No second attempt is authorized yet.

## Validation and progress

The focused existing autodrive tests produced 4 passes and 6 failures (11 subtests passed). All six failures occur while serializing an unrestricted Mock controller's `pid` into the manifest, before driving or prompt construction. The same manifest field is present in baseline `0ac5edd`. No controller or test changes were made for this prompt experiment.

## Interrupted result

The run ended on a native-daemon observation timeout after its first 22-frame phase. The native event confirms that phase executed successfully in 2.35 seconds, but its following screenshot did not return within the transport's 15-second deadline. Thus the runner reports zero complete action/observation cycles. The remaining 38-frame phase was never sent. Cleanup also logged `Native daemon transport is closed`; the wrapper successfully toggled recording off and exported the capture.

- Actual preserved recording: **22 frames, 0.37 seconds**, not a completed minute. Target 3,597 was not reached.
- One policy decision: `cross + steer_right` for 22 frames, then planned `cross` for 38. The rationale correctly identified the left-curb starting position and no verified street opening.
- Final stored image: car remains near the original left curb. No right-lane entry, completed turn, or block return demonstrated. This trial cannot establish the prompt improvement's effectiveness.
- [Replay](../videos/stream-junction-minute-01.mp4), [recording provenance](../videos/stream-junction-minute-01.json), and [decision/native-event evidence](../evidence/stream-junction-minute-01.json).
- Lossless master remains under `.runtime/stream-junction/pcsx2/videos/`; all 22 PNGs and playback remain under `runs/stream-junction-minute-01/recording/`.
- Emulator PID **66528** remains alive. No controls were issued after the coordinator requested a global trial pause, and no restart/reset was attempted.

## Lesson and next improvement

This is an infrastructure interruption, not a driving-quality result. A successful input phase can be followed by a capture failure, so a zero completed-action count does not prove zero applied controls. Resume must preserve this partial progress and must never replay the already executed 22-frame phase. Next investigate the post-actuation screenshot timeout and paused-state isolation under concurrent instances, then coordinate continuation before changing any driving guidance. The near/far-curb hypothesis remains untested.
