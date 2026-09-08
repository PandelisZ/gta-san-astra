# Autonomous attempt videos

Each MP4 is actual emulator footage at simulation speed. Model-thinking pauses do not add video frames. The adjacent JSON records the model, control implementation, measured duration, and outcome.

Driving controls are chosen by Astra from screenshots. Resetting a save state, limiting an attempt, capturing frames, and exporting a video are experiment orchestration, not a replayed driving script. We change general perception/control guidance between attempts; we do not bake in a sequence of steering or throttle inputs.

The target is one minute of recorded simulation per attempt, followed by a reset to `quiet-tahoma`. The first historical video, `block-attempt-03.mp4`, is shorter (51.65 seconds): it exposed that requested frame advances are not a reliable delivered-frame count. Its duration is preserved honestly rather than padded or sped up.

Lossless masters and every decoded PNG remain under ignored `.runtime/` and `runs/` folders. These compact MP4 copies are deliberately tracked in Git.

| Video | Observed outcome |
| --- | --- |
| [Block attempt 03](block-attempt-03.mp4) | Two right turns, curb/pole recovery, and traffic yielding. No completed block loop. |
