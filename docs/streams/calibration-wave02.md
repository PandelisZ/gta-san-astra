# Closed neutral calibration after wave 02

Recovery driver PID75227 had exited and its part3 manifest recorded capture stop before calibration began. Root reserved route PID69729 exclusively. The other three game processes still existed but their drivers were stopped; this was not a single-emulator-process experiment. Target stayed in its existing paused scene; no reset, steering, throttle, or explicit focus commands were used. Each clip used only 60 neutral frame-advance pulses and recording toggles.

| Condition | Pulse interval ms | Final decoded frames / pulses | Native pulse elapsed | Helper observations | Evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| pair1/baseline | 90 | 18 / 60 | 6.416s | 0 | [report](/Users/pz/w/oaihackathon/runs/calibration-wave02-pair1/baseline/report.json) |
| pair1/with-helper | 90 | 19 / 60 | 6.414s | 5 | [report](/Users/pz/w/oaihackathon/runs/calibration-wave02-pair1/with-helper/report.json) |
| pair2/baseline | 90 | 16 / 60 | 6.388s | 0 | [report](/Users/pz/w/oaihackathon/runs/calibration-wave02-pair2/baseline/report.json) |
| pair2/with-helper | 90 | 23 / 60 | 6.405s | 5 | [report](/Users/pz/w/oaihackathon/runs/calibration-wave02-pair2/with-helper/report.json) |
| solo180/baseline | 180 | 30 / 60 | 12.194s | 0 | [report](/Users/pz/w/oaihackathon/runs/calibration-wave02-solo180/baseline/report.json) |

Both packet counts and independently decoded-frame counts agree for every closed clip. Homebrew ffprobe could not load libx265.216, so the working recording.ffmpeg_path executable provided explicitly labeled packet and decode counts. These are finalized counts after capture stop and stable file size, not live-buffer lower bounds.

Codex/ChatGPT PID39035 was foreground before and after all five clips. Both helper conditions made five successful lane-PID69702 observations, with times retained in the reports. There is no consistent helper penalty: paired counts were 18 versus19 and16 versus23. Capture helper launch is therefore not necessary for the observed deficit. Endpoint snapshots cannot exclude transient focus changes during a clip.

At180ms, the solo clip stored30/60, versus16–18/60 at90ms. Increasing the interval improved delivery, but did not establish one stored frame per request. No further interval or focus tests were run in this batch.

Source supports several distinctions: VMManager::FrameAdvance assigns one pending count rather than accumulating requests; the native response counts emitted pulses, not simulator acknowledgments. Recorder duplicate skipping is disabled during video capture, the queue blocks when full, and previously inspected packet timelines lacked holes. These favor a request/processing issue over post-delivery encoder omission, while leaving pre-delivery omission and background scheduling unproven. No exact simulator-VSync completeness claim follows from these files alone.

A final read-only screenshot confirms Paused but still shows a red recording-style marker, so the pixels alone do not verify recording OFF: [final route state](/Users/pz/w/oaihackathon/runs/calibration-wave02-final-state/20260908-141723-8078cd96/frame-1788902243172007000.png). Every run report records a successful stop toggle. No controls were sent after the180ms experiment.

The next requested comparison is a separately authorized focused90ms neutral60 test after the other emulator processes are closed. That changes process count and foreground state together, so a positive result alone would not separate their effects.

Recorder state verification: route emulog contains matched start/stop entries for all five files, ending with `Stopped capturing video` and `Stopping encoder thread` for the14:16:45 file at2602.4995, with no later start. This supports capture OFF despite the stale marker in the paused display. Capture state is established by the log, not by that screenshot marker.

## Authorized single-process focused follow-up

Root confirmed only PCSX2 PID69729 remained, then authorized one explicit-focus90ms neutral60 test. Focus returned success; foreground snapshots before and after both identify PCSX2 PID69729. The final result was **23 decoded frames and23 packets from60 pulses**, native elapsed6.495s. [Report](/Users/pz/w/oaihackathon/runs/calibration-wave02-single-focused90/baseline/report.json). Route emulog confirms the14:18:39 capture stopped and encoder thread stopped at2710.1042, with no later start at inspection.

Removing other emulator processes and explicitly foregrounding the target did not restore1:1 delivery at90ms. This weakens a foreground/background-only explanation. No additional controls were issued after this bounded test, and no90ms one-pulse/one-frame guarantee is supported.

## Invalid350ms attempt and source cost boundaries

An authorized60-pulse350ms follow-up was interrupted by the existing Controller15-second native timeout; a complete burst requires at least21.6seconds. No60-pulse delivery ratio can be inferred. Cleanup and emulog confirm the14:19:19 capture stopped at2758.9622. [Failure report](/Users/pz/w/oaihackathon/runs/calibration-wave02-single-focused350/baseline/report.json). No retry was issued at this point.

Keyboard down/up events enqueue CPU-thread InputManager callbacks (`DisplayWidget.cpp:274`, `QtHost.cpp:1252`); the source does not simply poll a10ms key level. Each frame-step pause waits for VU and GS (`VMManager.cpp:280–282`), while resume resets frame limiter/metrics and emits UI updates including display refocus (`MainWindow.cpp:2457–2478`). These are plausible per-step costs; none measures an actual250ms processing delay. The present evidence cannot distinguish slow pause/resume processing from missing OS event delivery conclusively.


## Completed350ms retry

After root adjusted the controller timeout to cover the requested pulse wall time, the authorized fresh350ms solo retry produced **60 decoded frames and60 packets for60 pulses**. Native elapsed was 22.374seconds. [Report](/Users/pz/w/oaihackathon/runs/calibration-wave02-single-focused350-retry/baseline/report.json). This validates1:1 neutral delivery for this single scene/run at350ms; it does not establish a lower safe interval or guarantee arbitrary driving/render loads. No further controls were issued.
