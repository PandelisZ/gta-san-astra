# Transferable visual driving lessons

These are qualitative priors from earlier attempts, not current vehicle state or a route to replay. A reset clears all completed-turn counts and location assumptions. Re-check every clearance in the new screenshots.

- Short throttle followed by braking often produced little useful travel. An observation boundary is not a reason to stop when a clear, aligned corridor supports continued motion. Conversely, a door interaction can interrupt movement without a physical blockage.
- Turning attempts with short steering phases followed by straight coasting advanced across the destination centerline before achieving the required yaw. Releasing steering while still diagonal preserves that diagonal heading. Choose action and thinking controls as one trajectory; finish the required rotation without coasting toward the far curb.
- A commanded handbrake hold did not imply an immediate stop: one junction sequence advanced roughly a car length during the following interval before becoming stationary. This is a rough observation at that particular speed, not a universal braking distance. Establish enough stopping room before committing.
- PCSX2's visible input display confirmed R1 remains held after both a new end-of-action press and a press already active during the action. It cleared after explicit release. This verifies input persistence, not braking strength.
- Reverse-left can rotate the nose right while retreating; observed rear clearance must support the whole maneuver. Nearby vehicles can remove that clearance while the model thinks.

Sources: flow-minute-03-review.md, flow-minute-04-review.md, flow-minute-05-main-review.md, and input-persistence-check.json. Never treat these old scenes as the current scene or count their turns in a fresh attempt.
