# Every-frame recording and simulation-speed playback

The complete visual record is separate from Astra's sampled observations. PCSX2's built-in recorder captures display frames inside the emulator, including frames between the model's 60-frame decisions. It writes a lossless **FFV1 / bgr0 MKV master** beneath `.runtime/pcsx2/videos/`. That directory and all exports under `runs/` are Git-ignored.

This uses the emulator's GS/VSync path, not a desktop screen recorder. In PCSX2 2.8.2, [GSRenderer::VSync](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/GS/Renderers/Common/GSRenderer.cpp) submits frames while capture is active and disables duplicate-frame skipping. [GSCapture](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/GS/GSCapture.cpp) advances timestamps per delivered frame and waits for the encoder when its queue fills. Paused model-thinking gaps add no emulated VSyncs and therefore no extra capture frames. Playback follows simulation time even when the experiment takes longer on the wall clock.

## Record

The next setup/scenario launch installs the recording configuration and F12 binding. The recorder does not start automatically. Quit PCSX2 before launching the configured scenario, then start capture **before** beginning the driving run:

```sh
GAME_ISO="/absolute/path/to/San Andreas.iso"
uv run python scripts/scenario.py launch stationary-car --iso "$GAME_ISO"
uv run python scripts/recording.py status
uv run python scripts/recording.py toggle
```

The [F12 hotkey](https://github.com/PCSX2/pcsx2/blob/v2.8.2/pcsx2/GS/GS.cpp) starts/stops capture directly; there is no filename dialog. PCSX2 chooses a timestamped name in the configured video directory. Coordinate toggles with the sole active driver. The status command reads configuration and files; it does not claim that recording is active. Check the capture indicator and the file before running the experiment.

After driving, toggle once to stop and finalize the master:

```sh
uv run python scripts/recording.py toggle
uv run python scripts/recording.py status
```

Keep the master MKV until a lossless archive has been verified. Audio is disabled in this visual evaluation capture. Starting or stopping the recorder does not advance the game or toggle emulation pause.

## Export all frames and playback

Use the actual MKV path shown by `status`:

```sh
uv run python scripts/recording.py export \
  ".runtime/pcsx2/videos/ACTUAL-CAPTURE-NAME.mkv" \
  --output "runs/recordings/driving-attempt-1"
open "runs/recordings/driving-attempt-1/playback.mp4"
```

The exporter decodes **every stored frame**, including duplicates, into numbered lossless PNG files and produces an H.264 MP4 at the master recording's timestamps. It retains the MKV and records its checksum, decoded frame count, export time, and output paths. The PNG folder is the requested all-frames archive; MP4 is the convenient playback derivative. It refuses to overwrite an existing export and refuses to store these outputs outside the repository's ignored `runs/` or `.runtime/` folders.

A working system FFmpeg is used when available. This machine's Homebrew FFmpeg has a missing x265 library, so the exporter can use an isolated `imageio-ffmpeg` wheel through `uv`; it does not change the system installation. `SAN_ASTRA_FFMPEG` selects an explicit executable.

The installed PCSX2 FFmpeg libraries were directly checked for FFV1, Matroska, and bgr0 pixel-format support. That capability check and the source establish the capture mechanism. A completed recording and its decoded frame count establish what a particular run actually stored. Capture errors, graphics-device resets, or interrupted files still require review; successful encoding must not be assumed from requested frame counts alone.


After this run, frame-key timing was increased to 10 ms held plus 90 ms settling. A separate neutral 60-request calibration recorded and decoded exactly 60 frames. This is one observed calibration, not a guarantee under every load. The original 898-frame attempt is preserved in a verified lossless archive.

## Verified lossless archival

Seven finalized captures were transcoded from FFV1 to lossless RGB H.264 MKV to make room for concurrent experiments. Every decoded RGB24 frame hash, PTS, DTS, dimension and sample aspect ratio was compared. All 12,587 frames matched; inferred frame-duration metadata differs by at most 1 ms, while presentation timestamps are identical. The original codec files were removed only after both source and archive SHA256 checks passed. Individual PNG exports can be regenerated from these archives.

[Archive mappings](evidence/lossless-archives.json) record the original checksums and replacement paths. Historical run manifests retain their original capture paths and hashes; resolve those through this mapping. `scripts/archive_recordings.py` performs the verified transcode without deleting inputs.

## Interrupted attempts

`attempt.py --bridge-transport cli` selects the serialized short-lived capture path. If a run fails after sending controls, preserve its recording and continue the same paused game using `--no-reset --resume-from runs/PRIOR-RUN --target-recorded-frames REMAINING`. The resume file supplies prior visual context only; it never replays controls. Subtract the finalized prior capture's actual frames from 3,597, and keep both capture parts. A partial control phase may have executed even if its following screenshot failed. Count native action evidence and inspect the fresh image before continuing. A continuation segment alone does not prove a complete minute or a completed route.

Three redundant PNG exports (9,234 frames) were removed after comparing every RGB24 frame hash, dimension and sequence position against those verified archives. Every captured frame remains stored losslessly. [PNG archive mapping](evidence/png-archive-mapping.json) records the exact paths and counts; each old frame directory contains an `ARCHIVED.md` pointer. Model observation screenshots and published videos remain separate.
