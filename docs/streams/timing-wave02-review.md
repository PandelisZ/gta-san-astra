# Wave 02 timing investigation

Read-only snapshot while trials were active. No controls, timing changes, or captures initiated. Counts below are saved live packet-count lower bounds, not final flushed counts.

## Observations

The deficit is cross-stream. At the inspected checkpoints, lane had 2,771 stored frames / 3,180 requested (step 52); junction 3,059 / 3,600 (step 59); route 3,311 / 4,080 (step 67). Recent increments in all three were predominantly 36 per 60 requests, sometimes 24 or 48. The assertion that only route is affected is not supported by these logs.

Native 60-pulse elapsed time stays near 6.35–6.40 seconds. Median early versus recent native times were lane 6385 versus 6365 ms, junction 6387 versus 6380 ms, route 6404 versus 6389 ms. Recent policy latency medians were about 4.6–5.5 seconds. Junction controller wall times reached 29–41 seconds for a native loop lasting 6.3 seconds; the excess is outside the native pulse loop and consistent with lock/process overhead. It must not be counted as slower pulse spacing.

Degradation does not have one demonstrated common launch timestamp: lane steps 31–37 already returned 48 per 60, then step 38 returned 36; junction steps 36–39 returned 48 and step 40 returned 36; route was already returning 36–48 in that wall-time interval. The cumulative missing hundreds are much larger than the capture queue documented in source. This strongly suggests unfulfilled frame-advance requests or another upstream loss, rather than only a small fixed capture backlog. Final capture closure and recount are still necessary to distinguish permanent deficit from mux/codec buffering conclusively.

The inspected PCSX2 emulog files show capture starting normally, with no frame-map or encoding failure messages. Absence of log errors does not prove each key pulse reached the hotkey handler.

## Source-grounded mechanisms and limits

- `/tmp/sanastra-VMManager.cpp:2329`: `FrameAdvance` assigns `s_frame_advance_count = num_frames`; it does not accumulate requests. A subsequent request before the pending simulated frame completes can therefore fail to add another frame. The native loop acknowledges emitted events and elapsed sleeps, not consumed simulator frames.
- `/tmp/sanastra-GSCapture.cpp:138`: three frames in flight and six pending slots. The encoder waits for occupied slots at line 875. Map failure is explicitly warned at line 920 and may skip a frame, but no matching warning was found in inspected logs.
- `/tmp/san-astra-pcsx-source/Hotkeys.cpp:179`: frame advance triggers on key release.
- `/tmp/san-astra-pcsx-source/QtHost.cpp:803`: application focus loss clears keyboard bind state independently of `PauseOnFocusLoss`.
- `native/main.swift:11` creates `NSApplication.shared` without the daemon's `.prohibited` activation policy. This is a real source difference, but does not establish that launching this CLI changes the foreground application.
- `src/san_astra/control.py` allows capture under a separate global lock from actuation. Saved other-stream observation-call intervals overlap some recent native input intervals, but not all. These capture intervals include lock waiting, so they do not timestamp actual helper launch precisely. Recovery and external helpers were not exhaustively correlated. There are no saved focus-transition events proving a CLI-induced focus change.

Thus the proposed capture-helper/focus mechanism is plausible but unproven. The measured fixed native cadence plus non-accumulating frame-advance semantics is also plausible. Current evidence does not justify choosing one as the sole cause or patching live timing.

## Bounded neutral calibration after trials finish

First close each completed capture normally and compare the final packet count with its last live lower bound and requested count. Do not infer final deficit from live count alone.

Then use short separate neutral-only recordings on a stationary scene: (A) one PID, current pulse cadence, no concurrent capture helpers; (B) identical input while another PID is observed on a prescribed schedule. Flush and count each clip, keeping actual pulse count, native elapsed time, helper start/end times, and macOS foreground/focus-transition timestamps. Repeat the same conditions once to distinguish a repeatable effect from incidental scheduling.

Only if a repeatable difference emerges, change one variable: compare CLI versus daemon with the same focus policy, or lengthen pulse spacing with helper behavior unchanged. Do not simultaneously change transport, focus policy and interval. All requested game controls remain neutral, and success means closed-file frame counts per requested pulse, not visual displacement or native `ok` responses.

Evidence inputs: the current `stream-lane-minute-02`, `stream-junction-minute-02`, and `stream-route-minute-02` decisions.jsonl; their session events.jsonl; and each worktree's `.runtime/stream-*/pcsx2/logs/emulog.txt`.

## Recorder omission versus missed advances

Fresh profile inspection found `SkipDuplicateFrames=true` in all three profiles. This setting alone does not imply dropped captured duplicates: `/tmp/sanastra-GSRenderer.cpp:606` gates duplicate skipping on `!GSCapture::IsCapturingVideo()`. The capture block at line 811 is separate from presentation skipping.

A read-only packet scan of the live files subsequently counted lane 3,023, junction 3,347 and route 3,455 packets. Every adjacent packet PTS difference was 16 or 17 milliseconds; there were no timestamp holes. `DeliverVideoFrame` assigns/increments capture PTS before mapping and encoding (`GSCapture.cpp:895`), so a map/encoder omission after that point would ordinarily create a hole. Together with the blocking queue and absent map/encoding warnings, this weighs against post-delivery recorder drops as the explanation for the growing deficit.

This is not proof of every simulator VSync: the renderer can fail to deliver before PTS assignment if an intermediate/blank render target cannot be created (`GSRenderer.cpp:819,838`), and files cannot reveal such omissions through PTS gaps. The OSD capture timer also derives from `s_next_video_pts` (`GSCapture.cpp:1391`), so comparing that timer to recorded seconds would be circular evidence. No unvalidated conversion from the GTA clock was used.

The appropriate claim remains: all stored native video frames are retained; request counts do not establish consumed frame advances, and existing evidence favors an upstream/request-consumption issue over post-delivery encoding omission. Final flushed counts and neutral calibration are still needed.
