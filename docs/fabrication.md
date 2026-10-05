# Fabrication notes

## Before the first real cut

1. **Measure the sheet** with calipers in a few places. Enter the average as *Material thickness*.
   "3 mm" plywood is often 2.8–3.2 mm, and MDF/acrylic vary too.
2. **Cut the `fit-test` coupon** with your normal cut settings and current kerf guess.
3. Push the key into each slot and pick the clearance you want:
   - *press fit* (permanent, no glue): slightly tight, needs a firm push.
   - *sliding fit* (puzzle you take apart): goes in by hand without forcing.
4. Enter that value as *Slot clearance* for that material. If all slots are tight, increase *kerf*.
   If all are loose, decrease it.
5. Note the values per material (a table at the bottom of this file is a good place).

## Kerf vs clearance

- **Kerf** is the width of material the beam burns away (typically 0.1–0.25 mm on a CO₂ laser in
  3 mm plywood, depending on focus, power and speed). On export every outline grows by kerf/2 and every
  hole shrinks by kerf/2, so parts come out at nominal size.
- **Clearance** is deliberate play in slots and holes, added by the generator to the nominal design.

Set kerf so that a plain square comes out the right size. Then use clearance to tune how joints feel.

## Files

- SVG in millimetres. **Red `#ff0000` = cut**, **blue `#0000ff` = engrave/score** (line mode, low power).
  In LightBurn, importing the SVG creates one layer per colour; set Line/Cut for red and Line/low-power for blue.
- Holes come before outlines in the file so inner features are cut before a part can drop. Still, check the
  cut order in your software ("inner shapes first" in LightBurn's optimisation settings).
- DXF has layers `CUT` and `ENGRAVE`.
- Labels are stroked text, not fonts, so they survive import anywhere.

## Material notes

- Plywood: the grain direction matters for thin parts (spines, teeth). Thin features below ~1.5 mm break.
- MDF: strong in all directions, dusty, charred edges. Fits are more consistent than plywood.
- Acrylic: brittle, so avoid press fits (it cracks). Use positive clearance (+0.05…0.1).
- Cardboard (for prototypes): thickness ~1.5–4 mm, very forgiving. Great for testing a design before wood.

## Calibrated values

| Material | Machine | Thickness (measured) | Kerf | Clearance | Notes |
|---|---|---|---|---|---|
| | | | | | |
