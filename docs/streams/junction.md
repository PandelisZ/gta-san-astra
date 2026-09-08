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

## Minute 02: completed recorded minute

The coordinator fixed shared capture/input isolation, reset the same profile from `quiet-tahoma`, performed the neutral warmup, and handed back PID **69942**. This trial retained exactly the same driving prompt and goal. It integrated `control.py` and `daemon.py` from shared commit `90149e5` and selected CLI transport through a new `attempt.py --bridge-transport` option. During the run the coordinator atomically replaced the shared bridge with the live-process identity fix from `a31368e`; this did not change driving controls or the model policy. No reset, replay, or retry was needed during minute 02.

| Measurement | Result |
| --- | --- |
| Completed decisions | 79 |
| Requested frame advances | 4,631 |
| Live stored-frame lower bound at stop | 3,599 |
| Final flushed/decoded frames | **3,608** |
| Full recording duration | **60.19 seconds** |
| Git replay | **3,597 frames / 60.01 seconds** |
| Requested minus stored frames | 1,023 (77.91% stored/requested) |
| Wall-clock driver duration | 1,886.753 seconds |
| Transport/policy errors | None |

The stored/requested difference is measured; it does not by itself identify whether frame advances were unfulfilled or frames were dropped. The coordinator will run a separate neutral timing calibration after all drivers stop. Cadence was not changed during this trial.

### Driving result

The car entered the right lane from the left-curb baseline, approached the real first intersection, yielded to traffic, and completed a right turn onto the uphill road at roughly 31–33 seconds of recording. The inspected corner frames show the car turning through the street opening, without a visible inside-sidewalk shortcut. After the turn it straddled the centerline before correcting into the right lane. It then waited at the second red-light junction with crossing traffic/pedestrians and began a second right turn near the end. The final view remains oblique to that destination road: **one completed right turn, second underway, block loop and landmark return incomplete**.

Traffic crowded the first approach, including a light car immediately behind. The sampled review does not establish collision-free driving. Review covered 15 stored-frame milestones, including before/during/after the first turn and the final frame; decision rationales are retained separately from these observations.

- [Minute replay](../videos/stream-junction-minute-02.mp4)
- [Recording provenance](../videos/stream-junction-minute-02.json)
- [Selected decisions and measurements](../evidence/stream-junction-minute-02.json)
- [Stored-frame review sheet](../evidence/stream-junction-minute-02-contact-sheet.jpg)
- Full MKV and **all 3,608 PNGs** remain in the profile's `videos/` directory and `runs/stream-junction-minute-02/recording/`, respectively.

The hypothesis produced a real corner traversal in this run, but a single trial cannot establish causation. Slow lane alignment and long waits consumed much of the minute. A proposed future prompt refinement is to distinguish lane alignment, geometric turn readiness, and current traffic occupancy explicitly so uncertainty in one does not indefinitely obscure progress in the others. Do not apply it until after the coordinator's timing calibration and next-trial authorization.

PID **69942** remains paused in the same profile. Recording is finalized, and no further gameplay or cadence changes were issued after completion. No second trial is started.
