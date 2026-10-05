# vehicle

A push-toy car with rolling wheels, built from flat parts. No drawing needed: pick a preset and a scale.

## How it is built

```
            roof
        ___________
 wind- /           \  rear
screen/             \ window
_____/               \______
hood                    boot |  ← rear
|  front                     |
 \__(O)______________(O)____/   ← floor; axles above the floor, wheels outside the body
```

- **Side plates** (2): the side profile grown by `rim`, with corners rounded by `corner_radius`, axle holes
  (running fit), engraved windows/doors/wheel arches. Windows can be cut through instead (`windows=cut`).
- **Body panels**: one per profile segment (front, hood, windscreen, roof, rear window, boot, rear, floor),
  spanning between the sides with tabs through slots in both side plates (`joints.tab_slot`). At each crease
  the longer panel runs to the corner and the shorter one is trimmed to just touch it, so convex creases show a
  small V-notch (laser cuts are square).
- **Axles**: steel rod through running-fit holes in both sides, plus `bearing_pads` glued inside each side
  (longer bearing = less wobble). The axle turns with the wheels.
- **Wheels**: hub spacer + inner layer + (optional) narrower middle layer forming a groove for an O-ring tyre +
  **outer cap with no hole**, all glued onto the rod (press fit). No rod end is exposed.

## Trailers and the hitch

Trailer presets: `trailer-box` (open-top utility box with plank engraving), `trailer-flatbed` (low deck with a
headboard, wide enough to carry a toy car), `trailer-container` (20 ft container with corrugation and rear
doors, tandem axle), `trailer-caravan` (windows and door). Trailers have one axle (or a tandem) behind the
middle and a **support foot** under the front, so an unhitched trailer stands almost level.

**Hitch standard** (same for every vehicle cut from the same sheet thickness):

```
 car  ── floor ──┐                         ┌── floor ── trailer
                 └─ tongue ─[peg]           │
                            (ring)─drawbar──┘   drawbar glued on the trailer's floor tongue
```

- Towing (`rear_hitch`, default on for every preset, trailers too, so they chain): the floor extends
  backwards as a 10 mm tongue with an upright **peg**, a small plate (8 mm × 2t+3 mm) with a rounded top, tabbed
  through the tongue.
- Towed (trailers): the floor extends forwards; a **drawbar** plate glued on top of it ends in a **ring** (hole =
  peg diagonal + 1.5 mm) that drops over the peg and rests on the tongue. The ring is circular, so the trailer
  swings freely; the drawbar is long enough for ±35° before the bodies touch (checked by a test that couples
  cars and trailers in 3D at 0° and ±35°).
- `hitch_height` (default 8 mm, top of the tongue) fixes the floor height of **every** vehicle at
  `hitch_height - thickness`, so coupled vehicles sit level. When the wheels are automatic, they grow if needed
  to leave room for the axle above that floor. Use the same `hitch_height` and sheet for everything that should
  couple.
- No magnets: small neodymium magnets are a serious swallowing hazard for under-3s.

## Scale and proportions

Presets store real-world sizes (mm) of a typical car of each type: `sedan`, `hatchback`, `sports`, `jeep`,
`pickup` (covered bed), `van`, `bus`. Everything is divided by `scale` (1:N); `length` overrides the scale to fit
an exact model length. Common scales: 1:64 Matchbox (~7 cm), 1:43 (~11 cm), **1:36 (~13 cm, default)**,
1:32 (~14 cm), 1:24 (~19 cm).

`toy_proportions` (default on) makes the wheels 1.35x larger than scale. At true scale the wheels are too small
to run a 3 mm axle above the floor of a 3 mm-ply body below ~1:30; the generator says so.

The floor height is taken from the preset when possible, then clamped so the side plates clear the ground by
2 mm and the rod clears the floor by 1.5 mm.

## Fits

| hole | size | parameter |
|---|---|---|
| wheel layers, hub spacer | rod + `press_fit` | find with the `fit-test` hole strip: firm push, no turning |
| side plates, bearing pads | rod + `running_fit` | spins freely, no wobble |

Slots for the panel tabs use the usual `clearance`. Since everything is glued, a sliding fit (0…+0.05) is easier
to assemble than a press fit.

## Assembly (also in the generated notes)

1. Cut 2 rods to the length in the stats (`rod_length_mm`); file and scuff the ends.
2. Glue the bearing pads inside the sides, aligned with a rod through the holes.
3. Floor and panels into one side, second side on, check the axles turn, glue all joints.
4. Glue one wheel stack onto each rod end with epoxy/CA (rod bottoms on the cap); paper strip between spacer
   and side for play while gluing the second wheel.
5. Optional O-ring tyres. Sand, toy-safe finish (EN 71-3).

## Safety (it's for a toddler)

Everything is glued; no exposed rod ends; rounded side corners; windows engraved by default (no finger traps).
Wheels and small parts are a choking hazard for under-3s if they come off: check the glue joints regularly.

## Limitations / ideas

- Sides are parallel (no taper in plan view) and the body is a single box: no separate cab/box for trucks,
  no open pickup bed. Open-top trailers work because a profile segment can be marked `"open"` (no panel).
- The UI previews one vehicle at a time; coupling is only checked in tests.
- Wheels are always outside the body (toy style).
- Possible next: living-hinge roof (one bent strip instead of separate panels), custom profile input
  (points or SVG), steering front axle, spine-and-ribs (`cross_lap`) body variant.
