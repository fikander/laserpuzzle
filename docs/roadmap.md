# Roadmap

Ordered roughly by value / effort. Core work comes first because every generator after `stacked-layers`
needs real joints.

## Core

1. **Joint library: `core/joints.py`.** Reusable, tested functions that modify two parts' outlines so they
   meet with zero overlap:
   - `cross_lap(part_a, part_b)`: generalised half-lap from `stacked-layers`, for any two plates crossing.
   - `tab_slot(edge_part, face_part, n_tabs)`: tabs on an edge, matching slots in a face (car body panels).
   - `finger_joint(part_a, edge_a, part_b, edge_b)`: box corners.
   - `t_slot(..., screw="M3")`: bolt + captive nut, for things you want to take apart.
   - `living_hinge(region, pattern)`: bendable areas (car roofs, curved panels).
   Each joint works in 3D (uses both transforms) and is checked by the collision test.
2. **Assemblability check.** For each part, test whether it can slide out along its explode vector without
   colliding (sweep test). This catches "valid geometry, impossible to assemble".
3. **Better nesting.** Polygon-aware nesting (e.g. port of SVGnest/deepnest ideas, or `pynest2d`), part rotation
   by 90°/180°, filling holes of big parts with small parts.
4. **Image → vector input** (needed for cars): load PNG/JPG/SVG drawings, threshold + trace outlines
   (`potrace`/`opencv`), scale by a known dimension. SVG input directly via `svgelements`.
5. **Per-material presets.** Save thickness/kerf/clearance per material in a `materials.toml`, selectable in the UI.
6. UI: highlight the part on the sheet when it's clicked in 3D (and the reverse), an assembly-step animation,
   and project files (`*.lp.json` with generator + params) that can be saved and reopened.

## Generators

### `car-views`: car from 3 orthographic drawings + isometric reference

Input: side, front and top silhouettes (images or SVG), overall length, optional feature drawings (windows,
lights, door lines) as separate images or colour-coded layers.

Approach:

1. Trace the three silhouettes to polygons and scale them to the given length/width/height.
2. **Visual hull** = extrude(side, Y) ∩ extrude(front, X) ∩ extrude(top, Z), computed with manifold3d.
   This gives an approximate body solid.
3. Body construction, selectable:
   - *Panels*: two side walls (side silhouette, inset by t), floor, and a chain of transverse ribs (slices of the
     hull in YZ). Ribs cross-lap with a central longitudinal keel and have tab-slots into the side walls.
     Roof and hood are optional strips, or living hinges following the rib tops.
   - *Waffle*: longitudinal + transverse slices, cross-lapped (egg-crate), all from the hull. Easiest, robust.
   - *Stacked*: reuse `stacked-layers` horizontally (a quick prototype).
4. Wheels: discs (2–3 layers for thickness), axle holes, axle = dowel or a laser-cut cross-axle. Wheel arches
   are cut from the side walls. A wheel-position parameter can come from the side view (detect circles) or be manual.
5. Details: feature drawings projected onto the matching panel and **engraved**. Windows can optionally be cut through.

Risk: drawings that don't agree with each other (perspective, line weight). A UI step to align and crop
each view is probably needed.

### `figure`: humanoid from limb sizes

Parametric template: torso, head, upper/lower arms and legs, hands, feet. Each segment is two or three stacked
plates or a box. Joints are pin joints (a dowel through matching holes, with friction washers) or a ball-ish
cross-slot. Params: height and proportions (or measured lengths), thickness, joint type. Output works as
a poseable figure. Later: shapes from a reference silhouette.

### `mechanism`: gears, clocks, simple machines

- Involute spur gear generator (module, teeth, pressure angle, backlash), with layered gears for thickness.
- Gear train solver: target ratio → teeth counts, centre distances; frame plates with axle holes.
- Clock: gear train with ratios 12:1 and 60:1, frame, dial (engraved), weight-driven or hand-cranked.
  The escapement is the hard part and needs real prototyping.
- Consider wrapping the `boxes.py` frame generators for enclosures instead of re-implementing them.

### `marble-run`: GraviTrax-style track pieces

- Hex-grid or square-grid tiles (cut), plus height columns of stacked spacer layers.
- Track elements (straight, curve, drop, switch, merge) built as stacked layers with a channel cut through.
  Each layer is a 2D offset of the path centreline, and ball diameter + clearance gives the channel width.
- Route input: a simple JSON or grid-based description, or drawn in the UI later. The generator chooses
  heights so slope stays within a range (2–6% for rolling steel balls) and checks for drops.
- Physics sanity: centripetal limit on curves (banking via layer offsets), speed estimate along the route.

### Others

- `box-joint`: thin wrapper around boxes.py generators so their output flows through the same UI/export.
- `sliceform`: two families of interlocking slices (egg-crate) from any mesh. Small extension of the car waffle mode.
