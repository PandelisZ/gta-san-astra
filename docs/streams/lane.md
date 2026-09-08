# Lane stream

Worktree: `/Users/pz/.codex/worktrees/7cd5/oaihackathon`; owned emulator PID `66573`; profile `.runtime/stream-lane/pcsx2`. Base harness `0ac5edd`. No repository AGENTS.md exists in this checkout; supplied instruction to ignore unrelated work applies.

The prompt now distinguishes lateral right-lane entry from heading correction. It asks the screenshot-only policy to project the car's forward path against the lane corridor using curb/centerline convergence, then verify alignment before sustained acceleration. Model remains `gpt-6-astra`, low reasoning, fast service, 640px input throughout.

Baseline: shared immutable `quiet-tahoma`, launched paused with `--allow-multiple`, then 60 neutral redraw requests. Verified blue Tahoma by left curb, garden wall and orange motel. No manually selected gameplay controls.

Initial `stream-lane-minute-01` wrapper failed at its first daemon observation after 15 seconds, with zero decisions/actions. It stopped the recording and preserved the master and run evidence. Continuation `stream-lane-minute-01-continuation` uses the same paused game, no reset/replay, and CLI native transport. Added wrapper `--bridge-transport` selector for this operational fallback; default remains daemon. Policy unchanged.

Focused autodrive tests: 4 passed, 6 failed with Mock.pid JSON serialization. The same failures reproduce against unmodified HEAD in an isolated temporary fixture; unrelated to the prompt. No further testing planned for this prompt-only experiment.

Coordinator halted all trials after another stream showed unexpected recorded advancement. Sent SIGINT only to owned wrapper PID 67349, allowing owned driver cleanup and capture finalization. No further gameplay controls or reset. Emulator PID 66573 remains available for investigation.

Outcome: **incomplete**, 125 actual decoded frames (2.09 seconds), 2 model decisions and 120 requested/completed action frames. Target 3,597 frames was not reached. All 125 PNG frames and the 52.6 MB MKV master remain local. The 533-byte initial failed master is also preserved. Video: `docs/videos/stream-lane-minute-01-continuation.mp4`; metadata alongside it. Decision evidence: `runs/stream-lane-minute-01-continuation/decisions.jsonl`. No block or successful right-lane alignment claim.

Decision 0 identified the left-curb position and selected 12 frames of right steering with throttle, 18 throttle, and 30 coast. Decision 1 observed little lateral movement and selected 25 right+throttle and 35 coast. These controls were chosen exclusively by the screenshot policy. The last screenshot still places the car left of the road centerline; the policy had not reached the heading-correction stage. Input images during the continuation were 471x335 due to the window size, despite a configured maximum edge of 640.

Lesson: this short interrupted sample cannot evaluate the alignment improvement. Before another trial, resolve the coordinator's pause/input isolation concern and prove stable frame accounting across concurrent instances. Proposed next driving improvement, once a valid full trial exists: require explicit current versus desired road-relative heading in the route note so lateral progress cannot silently substitute for alignment. No policy changes were made during gameplay. Do not restart until coordinated.

## Corrected isolation trial: minute 02

Coordinator supplied reset PID `69702` and handed ownership back after a four-instance neutral isolation proof. It reported exactly 60 lane frames and zero frames in the other instances, with capture OFF afterward. The root performed initial neutral60 and an additional neutral60 for the proof. Shared control files restored from main `90149e5`: serialized CLI captures and explicit PID input without focus changes. Lane driving prompt unchanged. One `stream-lane-minute-02` trial launched with `--no-reset`, own PID/profile, CLI bridge, Astra low/fast and maximum image edge 640. Outcome recorded below.


### Minute 02 outcome

**Simulation minute completed; driving goal incomplete.** Final flushed capture contains **3,608 frames / 60.19 seconds**, versus **4,838 requested advances** across 83 model decisions (1,230 fewer stored frames than requests). The Git first-minute video has **3,597 frames / 60.01 seconds** with no padding. Live stopping count was 3,599; finalization added nine buffered frames. These counts establish the stored result, not the cause of the request/delivery gap. Wall time: 1,981.676 seconds. No driver or release errors.

[Minute video](../videos/stream-lane-minute-02.mp4) · [Video provenance](../videos/stream-lane-minute-02.json) · [Selected policy decisions](lane-minute-02-decisions.json)

The car entered the right side from the initial left curb, made one visibly confirmed right turn alongside the orange motel, drifted close to the right curb, then recovered toward the inner right lane. It waited at a red signal for much of the latter portion and began a second right turn into Los Colinas near the end. Final screenshot shows a diagonal position during that turn. No return to the starting garden wall/motel orientation is visible. This is one uncontrolled qualitative trial; no comparative improvement or collision-free claim.

The lane-entry prompt was followed in decision 2 with explicit countersteering, but stable alignment remained inconsistent. Decisions 15–23 repeatedly corrected curbward heading while coasting; decision 18 recognized near-zero motion and added powered correction. Decision 31 identified centerline overlap after recovery. Decision 49 onward recorded a stationary red-light wait, and decision 83 still recorded the second turn as underway. Indices here are one-based; evidence JSON uses zero-based steps.

Lesson: road-relative language made the correction intention explicit but did not ensure a stable lane trajectory. The next proposed prompt experiment should connect steering effectiveness to observed displacement and preserve a compact current/desired heading note, so near-stationary coasting corrections do not repeat. This is proposed only; no midtrial or subsequent policy change was made.

All 3,608 source PNGs are retained in `runs/stream-lane-minute-02/recording/frames`, with the original MKV under `.runtime/stream-lane/pcsx2/videos/Grand Theft Auto - San Andreas_SLUS-20946_20260908133709.mkv`. Full decision history and raw/model screenshots remain in the run directory. PID **69702** is left paused with recording stopped. No new trial, reset, or cadence adjustment performed. Coordinator owns the next timing-calibration decision.
