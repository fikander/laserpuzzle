"""Loading and normalising 3D models.

After `load_model`, every mesh follows the world convention: millimetres,
Z up, resting on z=0, centred on the Z axis (bounding-box centre in XY).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

UP_AXES = ["auto", "x", "y", "z"]


def _rotation_to_z(axis: str, flip: bool) -> np.ndarray:
    if axis == "z":
        r = np.eye(4)
    elif axis == "y":  # Y-up -> Z-up: rotate +90 deg about X
        r = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])
    elif axis == "x":  # X-up -> Z-up: rotate -90 deg about Y
        r = trimesh.transformations.rotation_matrix(-np.pi / 2, [0, 1, 0])
    else:
        raise ValueError(axis)
    if flip:
        r = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]) @ r
    return r


def load_model(
    path: str | Path,
    up_axis: str = "auto",
    flip: bool = False,
    height: float = 0.0,
    rotate_z: float = 0.0,
) -> tuple[trimesh.Trimesh, dict]:
    """Load a mesh and normalise it. Returns (mesh, info).

    up_axis: "auto" picks the longest bounding-box axis (good for figures).
    height:  if > 0, scale uniformly so the model is this tall (mm).
    rotate_z: spin around the vertical axis (deg) - chooses which side faces "front".
    """
    loaded = trimesh.load(str(path), force="mesh")
    if not isinstance(loaded, trimesh.Trimesh):  # pragma: no cover
        raise ValueError(f"could not load a mesh from {path}")
    mesh = loaded.copy()
    info: dict = {
        "file": str(path),
        "faces": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "original_extents": [float(v) for v in mesh.extents],
    }
    axis = up_axis
    if axis == "auto":
        axis = "xyz"[int(np.argmax(mesh.extents))]
    info["up_axis"] = axis
    mesh.apply_transform(_rotation_to_z(axis, flip))
    if rotate_z:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(rotate_z), [0, 0, 1]))
    lo, hi = mesh.bounds
    mesh.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    if height and height > 0:
        s = height / mesh.extents[2]
        mesh.apply_scale(s)
        info["scale"] = float(s)
    else:
        info["scale"] = 1.0
    info["extents"] = [float(v) for v in mesh.extents]
    return mesh, info
