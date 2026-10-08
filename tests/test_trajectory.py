"""Trajectories (a ball travelling through a model), their preview data and the check along the path."""

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point

from laserpuzzle.core.design import Design, Hardware, Part, Pivot, Trajectory, horizontal, vertical_yz
from laserpuzzle.core.geometry import rect
from laserpuzzle.core.validate import part_mesh, trajectory_collisions

T = 3.0
R = 8.0


def at(x, y, z):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def floor_design(path, pivots=None, wall=False):
    """A floor plate, a ball resting on it at x = 0, a trajectory along `path`; optionally a wall at x = 60
    hinged on a vertical axis at its edge (60, -20)."""
    parts = [Part("floor", rect(-20, -20, 120, 20), T, horizontal(0))]
    if wall:
        parts.append(Part("wall", rect(-20, 0, 20, 30), T, vertical_yz(60, T)))
    times = [float(i) for i in range(len(path))]
    d = Design(parts=parts, hardware=[Hardware("ball", "sphere", {"radius": R}, at(0, 0, T + R))],
               trajectories=[Trajectory("ball", times, [(x, 0.0, T + R + z) for x, z in path], pivots or {})])
    if wall:
        d.pivots.append(Pivot("gate", (60, -20, 0), (0, 0, 1), parts=["wall"], range=(-90, 0)))
    return d


def test_at_interpolates_and_loops():
    tr = Trajectory("ball", [0.0, 1.0, 2.0], [(0, 0, 0), (10, 0, 0), (10, 0, 20)], {"crank": [0, 90, 180]})
    pos, pose = tr.at(0.5)
    assert pos == pytest.approx([5, 0, 0]) and pose == {"crank": pytest.approx(45)}
    assert tr.at(2.5)[0] == pytest.approx(tr.at(0.5)[0])            # loops
    tr.loop = False
    assert tr.at(9.0)[0] == pytest.approx([10, 0, 20])               # clamped


def test_trajectory_problems():
    d = floor_design([(0, 0), (50, 0)])
    assert d.trajectory_problems() == []
    d.trajectories += [Trajectory("nut", [0, 1], [(0, 0, 0), (1, 0, 0)]),
                       Trajectory("ball", [1, 0], [(0, 0, 0), (1, 0, 0)]),
                       Trajectory("ball", [0, 1], [(0, 0, 0)]),
                       Trajectory("ball", [0, 1], [(0, 0, 0), (1, 0, 0)], {"crank": [0, 1]})]
    problems = " ".join(d.trajectory_problems())
    assert "no hardware named nut" in problems and "must rise" in problems
    assert "one point per time" in problems and "no free pivot named crank" in problems


def test_ball_rolling_on_the_floor_is_clean():
    assert trajectory_collisions(floor_design([(0, 0), (100, 0)])) == []


def test_ball_through_the_floor_and_into_a_wall_is_caught():
    hits = trajectory_collisions(floor_design([(0, 0), (40, -6)]))
    assert [h["part"] for h in hits] == ["floor"] and 0 < hits[0]["time"] < 1
    hits = trajectory_collisions(floor_design([(0, 0), (100, 0)], wall=True))
    assert [h["part"] for h in hits] == ["wall"]


def test_pivots_move_with_the_trajectory():
    """The gate swings open (away from the ball) before the ball gets there: no hit; left shut, it is hit."""
    path = [(0, 0), (30, 0), (100, 0)]
    assert trajectory_collisions(floor_design(path, {"gate": [0, -90, -90]}, wall=True)) == []
    assert trajectory_collisions(floor_design(path, {"gate": [0, 0, -90]}, wall=True))


def test_preview_carries_trajectories():
    from laserpuzzle.generators.base import Generator, _REGISTRY, register
    from laserpuzzle.pipeline import run

    @register
    class _Roll(Generator):
        id = "_test-roll"
        name = "test roll"
        description = ""
        params = []

        def generate(self, v, ctx):
            return floor_design([(0, 0), (30, 0), (100, 0)], {"gate": [0, -90, -90]}, wall=True)

    try:
        pv = run("_test-roll", {}).preview()
        tr = pv["trajectories"][0]
        assert tr["hardware"] == 0 and tr["times"] == [0, 1, 2] and tr["loop"]
        assert tr["points"][1] == [30, 0, T + R] and tr["pivots"] == {"gate": [0, -90, -90]}
    finally:
        _REGISTRY.pop("_test-roll", None)


def test_plate_with_many_slots_meshes_exactly():
    """A plate full of slots: its solid has the plate's volume (earcut used to fill a slot)."""
    from shapely.ops import unary_union
    from shapely import affinity
    slots = [affinity.rotate(rect(x, z, x + 9, z + 12), 2.3 * (-1) ** j, origin=(x, z))
             for j, z in enumerate(range(0, 200, 25)) for x in (10, 60, 110)]
    windows = [affinity.rotate(rect(25, z + 14, 105, z + 21), 2.3 * (-1) ** j, origin=(25, z))
               for j, z in enumerate(range(0, 175, 25))]
    plate = rect(0, -5, 130, 210).difference(unary_union(slots + windows))
    p = Part("post", plate, T, horizontal(0))
    assert part_mesh(p).volume == pytest.approx(plate.area * T, rel=1e-6)
