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
