# fit-test

A calibration coupon: a comb with `count` slots, widths `thickness + clearance_i` where clearance
steps from `first` by `step`, each engraved with its clearance. Comes with a 20 mm key cut from the same sheet.

With `rod_diameter` > 0 (default 3 mm) it also cuts a **hole strip**: holes of `rod_diameter + offset`, the
offset stepping from `hole_first` by `hole_step`, each engraved with its offset. Use it to find the
**press-fit** offset (wheel on axle, rod can't be turned by hand) and the **running-fit** offset (axle spinning
in a bearing without wobble) for your rod stock. Set `rod_diameter` to 0 to skip it.

Use it for every new material or machine. The procedure is in [../fabrication.md](../fabrication.md).

It is also the smallest example of a **parametric** generator (no input file): see the source in
`src/laserpuzzle/generators/fit_test.py`.
