# Route continuity stream

Worktree: `/Users/pz/.codex/worktrees/4ed4/oaihackathon`.
Shared harness: `0ac5edd`; isolated emulator PID `66584`.
Profile: `.runtime/stream-route/pcsx2`; shared read-only scenario `quiet-tahoma`.

## Pretrial change

The driving prompt now preserves an immutable visual start fingerprint (two distinctive landmarks and their left/right relationship to travel direction), explicitly marks a missed circuit unresolved, and requires landmark relationships plus road-edge heading to agree before claiming return. This is general screenshot-only route guidance, without a prescribed driving sequence. Existing model, low reasoning, fast service, input locks, and control policy remain intact.

Prepared baseline with 60 neutral frame requests before capture. One attempt planned: `stream-route-minute-01`, 640-pixel vision, target 3597 actually recorded frames. Every gameplay decision comes from the existing screenshot-only policy. No second attempt before coordination.

## Coordinated stop, no driving trial completed

The daemon startup failed before the first observation (`Native daemon timed out after 15 seconds`). Its driver reported zero decisions/actions/requests. Added an explicit `--bridge-transport cli` wrapper option, preserving daemon as default, then retried the same paused PID with the same prompt/model under `stream-route-minute-01-cli`. CLI captured successfully (199.56ms), but the coordinator requested all streams stop while investigating another stream's unexplained advancement. Sent SIGINT only to owned wrapper PID67558; it interrupted owned driver67588 and finalized this PID's recorder. Both processes exited; emulator PID66584 remains open. No further controls or reset were issued.

Both retained MKVs are 533-byte zero-frame files. Frame counting reports zero; no decodable frames or valid MP4 exists, so no video is manufactured. Each driver summary records zero decisions and zero gameplay frames requested. The CLI attempt was interrupted after7.054 wall seconds. The recorded minute target was NOT reached. Route return and the prompt improvement are untested.

The last CLI observation visibly says Paused and shows the Tahoma beside the starting garden wall, orange motel across the road, and clock17:19. This stream's evidence does not establish the cause of other streams' advancement.

![Paused route baseline after CLI capture](route-paused-start.png)

Machine-readable provenance: [startup evidence](route-startup-evidence.json). Raw evidence remains in `runs/stream-route-minute-01*`, with both masters under `.runtime/stream-route/pcsx2/videos/`.

## Validation and next step

`tests/test_autodrive.py`:4passed,6failed,11subtests passed. All six failures reproduce against isolated copies of the unmodified shared harness commit0ac5edd (mock controller PID is not JSON serializable). No live-policy changes were made in response.

Lesson: startup capture and confirmed paused isolation must be established before judging route behavior. Proposed next improvement: coordinator-owned no-input recording verification per isolated PID before restarting the unchanged route policy. After that gate, run one real minute and evaluate whether the fingerprint survives actual turns; do not tune from zero-decision startup failures.
