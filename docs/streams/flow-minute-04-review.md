# Flow minute 04

The car entered the first junction and nearly reached the right-turn heading, but lane recovery was incomplete. No completed turn or block return is verified. The original near-side pole was knocked down; later recovery approached the far sidewalk across the junction.

The run recorded 3,731 native frames (62.25 simulation seconds), ten decisions and nine applied actions. The full elapsed-time share video is 116.73 seconds and 7,178,250 bytes. Median inference latency was 9,590.55 ms; this single run does not establish a causal latency change.

Action 5 advanced from the near-side corner into the cross street with modest right yaw. Its following inference interval lasted 10.756 wall seconds and showed substantial additional travel toward the destination centerline despite declared handbrake input. The subsequent 60-frame handbrake action showed little additional motion. This does not distinguish residual/delayed braking from a control-persistence fault. Mapping and native code were inspected; physical braking persistence was not independently calibrated.

The lesson carried into the main-task trial is to distinguish near from far curb, recognize centerline overshoot separately from completed rotation, cross-check street orientation visually, and use observed stopping travel rather than requested braking as evidence. No hand-authored driving sequence was introduced.

[Full video](../videos/flow-minute-04.mp4) · [Video metadata](../videos/flow-minute-04.json) · [Decision evidence](flow-minute-04-evidence.json)

**Retention correction:** The raw recordings were retained when this run finished, but subsequent Codex task archiving removed the worktree containing them. The copied share video, decision evidence and final image survive in this checkout. See the [retention incident](../evidence/route-worktree-retention-incident.json).
