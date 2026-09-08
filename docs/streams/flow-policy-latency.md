# Shorter response comparison

Three recorded scenes from flow-minute-02 were evaluated with fresh policy sessions, the same images/history for each pair, and alternating original/compact order. The model remained `gpt-6-astra`, low reasoning, fast tier. No emulator controls were applied. This is a small latency comparison, not a replay or driving-quality test; its common prompt summarized the action timing rather than reproducing the original live timing context.

| Recorded decision | Original (seconds) | Compact (seconds) |
| --- | ---: | ---: |
| 0 | 9.756 | 4.768 |
| 5 | 7.413 | 7.104 |
| 10 | 6.373 | 5.502 |
| Median | 7.413 | 5.502 |

Compact output limits rationale to 120 characters, route memory to 180, and dynamics memory to 220. All six responses passed decision and 60-frame action-plan validation. The last pair made different choices around nearby traffic: original held handbrake, compact requested a short forward-left correction. Faster generation does not establish equal or better safety or route progress.

Flow-minute-03 tests these limits live. It also receives the existing trial duration, recorded elapsed lower bound and remaining upper estimate. Recording buffers mean these are approximate timing bounds; no vehicle telemetry or route progress is supplied. The one-minute reset, model, speed modes, visual inputs, and model ownership of every driving control remain the same.

[Raw paired responses and latency](../evidence/flow-policy-latency.json)
