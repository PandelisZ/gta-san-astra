# Pending baseline preparation

**Prepared only. Do not execute until the coordinator returns PID69729 and supplies the calibrated timing configuration.** Keep the minute recording and its policy unchanged. Apply the coordinator's current main next-wave policy/schema/control updates only after calibration; record the selected commit and timing with the preparation result.

Purpose: establish a new, stopped, road-aligned right-lane baseline near the current junction and its yellow hillside buildings. A future block attempt must return to this new visual fingerprint after a complete loop. This preparation is not a continuation or success claim for the original garden-wall route.

After explicit handback, use this bounded policy command from this worktree. It relies on the coordinator's approved timing implementation; no independent timing override is chosen here.

```sh
SAN_ASTRA_BRIDGE=/Users/pz/w/oaihackathon/native/astra-bridge \
SAN_ASTRA_PID=69729 \
SAN_ASTRA_PCSX2_INI=/Users/pz/.codex/worktrees/4ed4/oaihackathon/.runtime/stream-route/pcsx2/inis/PCSX2.ini \
uv run python scripts/autodrive.py \
  --pid 69729 --run-dir runs/stream-route-baseline-prep-01 \
  --steps 12 --frame-stride 60 --mode stepped \
  --model gpt-6-astra --reasoning-effort low --service-tier fast \
  --policy-transport app-server --bridge-transport cli \
  --vision-max-edge 640 --timeout 120 \
  --goal 'Prepare a new stationary reset baseline near the current distinctive junction with yellow hillside buildings and a signal ahead. Choose every gameplay control from screenshots. Safely stop fully within the RIGHT lane, parallel to the local road edges, clear of the intersection, sidewalks, traffic and pedestrians. Identify two distinctive fixed landmarks and their left/right relationship to the present heading. Do not try to complete a block or return to the original garden wall during this preparation. Confirm standstill by comparing fixed landmarks across consecutive observations separated by your chosen control phase; a Paused overlay alone does not prove zero vehicle motion. Set stop=true only when visible standstill, road alignment, right-lane position and clearance agree. If the bounded preparation ends without that evidence, report incomplete rather than claim readiness.'
```

Review the final observation pair and decision note before saving. If standstill/alignment/clearance are not established, do not capture a scenario or choose manual corrective driving. Report the outcome for coordination.

If the evidence passes, the existing snapshot helper acquires the per-PID controller lock. F1 is an opaque setup save, not a gameplay phase. No extra neutral advancement is needed for the snapshot itself:

```sh
SAN_ASTRA_BRIDGE=/Users/pz/w/oaihackathon/native/astra-bridge \
SAN_ASTRA_PID=69729 \
SAN_ASTRA_PCSX2_INI=/Users/pz/.codex/worktrees/4ed4/oaihackathon/.runtime/stream-route/pcsx2/inis/PCSX2.ini \
uv run python scripts/scenario.py \
  --scenarios /Users/pz/w/oaihackathon/.runtime/scenarios \
  capture right-lane-junction \
  --iso '/Users/pz/Documents/Games/Grand Theft Auto - San Andreas (USA) (v3.00).iso'
```

No `--replace`: preserve any existing scenario and `quiet-tahoma`. Retain screenshot pair, model decisions, scenario manifest/checksum, timing choice and source commit. The coordinator must visually verify a restore before using the new baseline for comparisons.
