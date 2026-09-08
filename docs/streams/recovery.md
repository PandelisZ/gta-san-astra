# Recovery stream

Worktree: `/Users/pz/.codex/worktrees/a761/oaihackathon`, branch `pz/stream-recovery`, shared harness `0ac5edd`.

Emulator PID: **66602**. Exclusive profile: `.runtime/stream-recovery/pcsx2`. Shared read-only `quiet-tahoma` scenario. No other emulator PID was targeted.

## Prompt improvement

Require evidence of backward translation relative to a fixed curb/pole and front-corner clearance before ending recovery. Camera swing and wheel spin do not establish escape. Preserve pending recovery in the visual route note. No model or driving policy changes were made after launch.

## Invalid attempt, paused for coordination

`stream-recovery-minute-01` selected screenshot-only `gpt-6-astra`, low reasoning, fast policy, 640-pixel vision input. Target was 3597 actual stored frames. **The target was not reached and no autonomous driving was evaluated.**

A first startup failed before controls because the daemon executable was incorrectly named; its logs remain in `runs/stream-recovery-minute-01-launch-error`. Corrected to `/Users/pz/w/oaihackathon/native/astra-daemon`, continuing the same game without reset.

The neutral 60-request warmup completed and its screenshot showed the blue Tahoma beside the starting garden wall at 17:19. The actual wrapper then failed on its first screenshot: `Native daemon timed out after 15 seconds`. The driver recorded **zero decisions and zero actions**. The wrapper stopped recording and exported **981 actual frames / 16.37 seconds**, retaining the full master and all PNGs. The final frame shows CJ on foot outside County General with the death tutorial. The cause is unresolved; this is evidence of a harness/state-isolation problem, not policy driving performance. A subsequent explicit-PID read-only screenshot was captured for diagnosis.

- Git replay: [`../videos/stream-recovery-minute-01.mp4`](../videos/stream-recovery-minute-01.mp4)
- Metadata: [`../videos/stream-recovery-minute-01.json`](../videos/stream-recovery-minute-01.json)
- Decisions/errors: `runs/stream-recovery-minute-01/decisions.jsonl`
- Master: `.runtime/stream-recovery/pcsx2/videos/Grand Theft Auto - San Andreas_SLUS-20946_20260908132752.mkv`
- Every frame: `runs/stream-recovery-minute-01/recording/frames/`
- Warmup image: `runs/20260908-132656-eb77ab85/frame-1788899243558183000.png`
- Read-only followup: `runs/20260908-132848-a6751bf1/frame-1788899328050661000.png`

Root instructed all streams to pause. Wrapper has exited and capture is finalized. No reset/restart or further controls will be issued until coordinated. The emulator PID remains available for diagnosis.

## Validation and next step

Focused autodrive tests: 4 passed, 6 failed (11 subtests passed). Failures occur while serializing the mock controller PID before policy execution; the prompt-only change does not touch that manifest code. Global focus and per-PID locks were preserved.

Lesson: a policy trial needs evidence that only its requested controls advance its game; recording duration alone cannot establish autonomous driving. Next improvement should verify paused observation/capture and process isolation across simultaneous instances before retrying this unchanged recovery prompt. Block completion and effective reversing remain untested.

## Minute02: same-game continuation in progress

Root reset/warmed a new owned PID **69719** and verified four-game neutral input isolation. Imported shared `control.py`/`daemon.py` from `90149e5`; explicit PID input avoids activation and CLI captures share a lock. Added wrapper options for CLI transport, visual resume context, and remaining recorded-frame targets.

The unchanged recovery prompt ran on CLI transport with Astra low/fast:

1. `stream-recovery-minute-02`: 96 actual frames, 2 decisions. Screenshot failed after successful 12-frame steering phase with a false PID-validation error; final 24-frame phase never executed.
2. After root rebuilt shared CLI with `a31368e`, resumed the same game without replay/reset as `stream-recovery-minute-02-part2`, targeting3501 frames. Six more decisions produced360 actual frames. Screenshot failed again after the final18-frame handbrake phase. **456 total actual frames retained;3141 remain.**

Part2 visibly backed away from the motel curb across toward the garden curb. The model explicitly retained pending recovery and worked on heading alignment. Screenshot `runs/stream-recovery-minute-02-part2/20260908-133955-ca6e1abc/frame-1788900098673600000.png` confirms the car transverse to the road with its rear near the garden sidewalk. Effective reverse travel is demonstrated; a right-lane recovery and block completion are not yet proven.

Both errors occurred in capture after successful input, so no prior control is safe to replay. Every native action and PNG is retained. PID69719 remained alive. Root is coordinating a transport fix before the next same-game continuation. Policy/model unchanged.
