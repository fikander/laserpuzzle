# stacked-layers

Slices a 3D model into horizontal layers with gaps between them and holds them together with a central
connector. Made for chess pieces, it also works for vases, busts and other mostly-vertical objects.

## Pipeline

1. `load_model`: auto up-axis (longest), optional flip / rotation, scale to *Height*, centre, base on z=0.
2. Layers: `n = floor((H − t) / pitch) + 1`, `pitch = t + gap`. Layer *i* occupies `z ∈ [i·pitch, i·pitch + t]`.
3. Outline per layer: section at mid-height (`middle`), or union (`max`) / intersection (`min`) of the sections
   at bottom, middle and top. Then a morphological opening by *Smallest feature* removes slivers.
4. Connector (below), then optional engraving of the next layer's outline onto each layer.

## Connector: `spine` (default)

A single upright plate in the XZ plane through the model's centre. Its shape is the model's XZ silhouette
inset by *Spine inset*, but never thinner than *Spine minimum width* (still clipped to the silhouette).

Each layer meets the spine in a **half-lap**. With `[a, b]` the spine's extent at the layer's height and
`mid = (a+b)/2`:

- the spine gets a slot `x ∈ (−∞, mid]`, height `t + clearance`, open to its −X edge,
- the layer gets a slot `x ∈ [mid, +∞)`, width `t + clearance`, open to its +X edge.

Assembly: hold the spine with slots facing −X and push each layer onto it moving towards +X. Layers lock
vertically on the spine and can't rotate. Between layers the spine shows the model's silhouette.

Visible consequences:

- Every layer has a thin notch from the centre to its +X edge. Use *Rotate about vertical* to put that
  side at the back.
- The spine's −X half becomes a comb. With very small gaps the teeth get thin. Keep gap ≥ thickness for wood.

Warnings you may see:

- *detached islands dropped*: the section has pieces not connected to the spine line (e.g. a horse's ears).
  Rotate the model, or accept the loss.
- *spine wider than the layer*: at thin necks the spine minimum width exceeds the layer. Lower the minimum width
  or increase the inset.
- *joint only X mm long*: weak joint. Increase the spine minimum width.

## Connector: `dowel`

A bought round rod through a hole in every layer, with laser-cut **spacer rings** filling the gaps. The gap
is rounded to a whole number of sheet thicknesses. Hole = dowel Ø + clearance. Measure your dowel: "6 mm"
beech dowels are often 5.8–6.1 mm. Simple and strong, and no notches are visible. The dowel shows at the top
unless you sand it flush.

## Parameters worth tuning

| Param | Effect |
|---|---|
| Height | Final size. Chess: king ~95 mm, pawn ~50–60 mm |
| Gap between layers | Bigger gaps look airier and show more spine, but the outline gets coarser |
| Layer outline | `max` never undercuts (good for tops of balls), `min` never overhangs |
| Smallest feature | Raise it if thin bits break off when cutting |
| Rotate about vertical | Which plane the spine follows / where the notches face |

## Limitations / ideas

- One spine only. A cross spine (two perpendicular plates) would need a different joint, for example layers
  in two halves or a twist-lock. It's a nice next step for rotationally asymmetric pieces (knight).
- Layers are always horizontal and parallel. Variable layer spacing (denser where the profile changes fast)
  would improve fidelity.
- No base plate option yet.
