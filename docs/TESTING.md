# Observed validation state

This record distinguishes implementation checks, visible gameplay, and measured timings. It describes the September 8, 2026 hackathon run on this Mac with PCSX2 2.8.2.

## Live path

- ScreenCaptureKit captures the actual emulator window; the default titlebar crop removes 32 pixels.
- Keyboard input and paused frame advancement were exercised in the PS2 BIOS and San Andreas.
- CLI and MCP observation paths returned actual screenshots. The early [BIOS evidence package](EVIDENCE.md) records those checks and their narrower scope.
- Astra low entered a Blista Compact in the playable game, and a paused road baseline was captured.
- The current baseline was restored by quitting PCSX2 and launching the named scenario. Its first GS output was black. A total of **66 neutral frame-advance requests** restored the visible car scene; the displayed clock changed from **16:56 to 16:57**. This establishes a visual restore, not a bit-exact screenshot or unchanged-world replay.
- The run at local `runs/driving-demo-01` completed **20 model decisions and 20 actions**, with no runner or release error recorded.

The baseline screenshot and sanitized snapshot record are [gta-stationary-car.png](evidence/gta-stationary-car.png) and [stationary-car.json](evidence/stationary-car.json). The full save-state file remains local and is never sent to the model.

## Recorded driving configuration

| Setting | Recorded value |
| --- | --- |
| Model | `gpt-6-astra` |
| Reasoning / service tier | `low` / `fast` |
| Policy transport | Persistent Codex app-server |
| Native transport | Persistent daemon |
| Execution | Paused, stepped simulation |
| Observation stride | 60 frame-advance requests per decision |
| Driving steering plan | First 12 frames steer; next 48 release steering and retain other controls |
| Model images | Longest edge 512 pixels, JPEG quality 65, RGB |
| Policy context | Latest two processed screenshots plus its own action history and task instructions |

The plan is logged before execution. Only the final observation of a burst feeds the next decision; intermediate raw captures can remain in the evidence. RGB preserves color information. JPEG compression reduces transport bytes; image dimensions and model detail handling affect vision-token usage.

## Measured run summary

Values below come from `runs/driving-demo-01/run_summary.json`, whose final status is `completed`.

| Measurement | Value |
| --- | ---: |
| Decisions / completed actions | 20 / 20 |
| Requested frame advances | 1,200 |
| Wall time | 273.177 s |
| Median model-decision latency | 7,483.21 ms |
| Median screenshot capture | 97.69 ms |
| Median action plus capture | 2,759.74 ms |
| Observed decisions per wall second | 0.0732 |
| Runner / release errors | None recorded |

Individual inference calls vary and take multiple seconds. At nominal NTSC 59.94, 1,200 requested VSyncs correspond to about 20.02 game seconds; this arithmetic does not independently certify delivery of every frame. The paused loop is **not a realtime wall-clock driving claim**. A faster isolated warm model response elsewhere is not substituted for the driving run's actual median.

Completed actions establish that the loop ran. They do not establish lane-keeping accuracy, collision-free driving, distance traveled, or a benchmark score. Those outcomes require review of the actual images and native recording.

## Recording and remaining evidence

Native recording is configured separately from model observation. FFV1 / bgr0 MKV captures go to the ignored `.runtime/pcsx2/videos` directory. [The recording guide](RECORDING.md) explains the emulator capture path, all-frame PNG export, and simulation-timestamp playback. The completed capture and its export must be inspected before claiming recording completeness for a specific run.

The latest source and unit checks are separate from the gameplay observations above. No tests were run to produce this documentation update, and no additional emulator inputs were sent.


After this run, frame-key timing was increased to 10 ms held plus 90 ms settling. A separate neutral 60-request calibration recorded and decoded exactly 60 frames. This is one observed calibration, not a guarantee under every load. The original 898-frame attempt is retained unchanged.
