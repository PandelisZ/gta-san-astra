# Driving observations and revisions

These are observations from real runs, not physical parameters read from the game. Astra still chooses every control phase from screenshots.

## Bounded steering was insufficient for corners

The original 12-frame steering pulse could make corrections but could not finish a right-angle turn. In block attempt 03, the first right turn needed roughly 80 steering frames across successive observations. The controller now accepts model-selected phases within each burst; the model must verify the resulting heading rather than assume a commanded turn happened.

## Recovery needs clearance at the front of the car

Block attempt 03 repeatedly reversed 12–15 frames and then tried forward motion while its front corner was still beside a pole. Guidance now distinguishes brief braking from intentional reversing, permits longer reverse motion when the observed rear path is clear, and requires visible front clearance before returning to forward travel.

## A passed junction is no longer a usable entrance

Minute attempt 04, steps 3–6: the real right-hand junction was visible under the first signal gantry at step 4. By step 5 its mouth had passed; the car was beside continuous curb and a low wall. The policy still described an opening and steered right, mounting the wall. Strong forward movement with little heading change suggests approach timing also mattered; the screenshots do not establish exact speed or turning radius.

Applied after minute attempt 04: revalidate the curb ends and continuous street corridor in the newest image before committing. If the entrance has passed, seek another junction rather than forcing the turn. Compare recent forward displacement and heading change when deciding how much motion to command near a corner. This is general visual-control guidance, not a memorized route or action sequence.

The next attempt uses a 640-pixel longest image edge instead of 512 to provide more curb/opening detail. This is an experimental quality change, not a measured improvement claim. Right-hand lane use is explicit following the user correction.

## Road-relative heading

Minute attempt 05 confused a screen-upright car with alignment to the road. The chase camera follows the car while curbs and the centerline reveal a diagonal trajectory. Releasing steering does not cancel that heading. The next policy explicitly describes lane position, heading relative to road edges, and movement relative to fixed landmarks before choosing controls. This improvement remains to be evaluated in the parallel streams.

## Next-wave motion memory (prepared after early wave 02 review)

The policy now has a separate `dynamics_note` for visually observed motion, response to previous controls, and prediction errors. Navigation landmarks and turn counts remain in `route_note`. This addresses recovery's underestimated reverse travel and lane correction that consumed curb clearance without enough heading change. The prompt compares recent displacement with remaining clearance and distinguishes requested braking from observed standstill. Fixed example ranges for correction duration were removed so the model must use its observed response. Every control phase remains model-selected.

This revision is prepared for the next trial wave; it was not injected into ongoing minute-02 policies. Its driving benefit is unproven until those subsequent recordings are reviewed. See [the image-grounded review](streams/early-wave02-review.md).
