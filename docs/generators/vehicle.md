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
  no open pickup bed.
- Wheels are always outside the body (toy style).
- Possible next: living-hinge roof (one bent strip instead of separate panels), custom profile input
  (points or SVG), steering front axle, spine-and-ribs (`cross_lap`) body variant.
