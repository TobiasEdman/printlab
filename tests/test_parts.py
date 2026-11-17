"""STEP import, rotation onto the bed and the axis-aligned side comparison.

tests/data/box_10x20x30.step is a 10 x 20 x 30 mm box written by gmsh's
OpenCASCADE kernel (gmsh.model.occ.addBox, gmsh.write), so the STEP path runs in
CI without a third-party CAD file.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from printlab import csg, parts
from printlab.cli import main

BOX_STEP = Path(__file__).parent / "data" / "box_10x20x30.step"


def mushroom() -> trimesh.Trimesh:
    """A 10 mm stem under a 30 mm cap: the cap's underside overhangs when upright."""
    stem = trimesh.creation.box([10, 10, 20])
    stem.apply_translation([0, 0, 10])
    cap = trimesh.creation.box([30, 30, 5])
    cap.apply_translation([0, 0, 22.5])
    return csg.union([stem, cap])


def two_boxes() -> trimesh.Trimesh:
    a, b = trimesh.creation.box([10, 10, 10]), trimesh.creation.box([10, 10, 10])
    b.apply_translation([30, 0, 0])
    return trimesh.util.concatenate([a, b])


def test_step_loads_as_one_closed_solid_in_mm():
    mesh = parts.load_step(BOX_STEP)
    assert mesh.units == "millimeters"
    assert mesh.is_watertight and len(mesh.split(only_watertight=False)) == 1
    assert np.allclose(sorted(mesh.extents), [10, 20, 30], atol=1e-4)
    assert mesh.volume == pytest.approx(6000, abs=0.01)


def test_step_units_come_from_the_file(tmp_path):
    text = BOX_STEP.read_text()
    assert text.count("SI_UNIT(.MILLI.,.METRE.)") == 1
    metres = tmp_path / "box_in_metres.step"
    metres.write_text(text.replace("SI_UNIT(.MILLI.,.METRE.)", "SI_UNIT($,.METRE.)"))
    assert np.allclose(sorted(parts.load_step(metres).extents), [10000, 20000, 30000], rtol=1e-6)


def test_other_formats_are_refused(tmp_path):
    trimesh.creation.box([0.01, 0.02, 0.03]).export(tmp_path / "metres.glb")
    with pytest.raises(ValueError, match="expected one of"):
        parts.load(tmp_path / "metres.glb")
    with pytest.raises(SystemExit) as stop:
        main(["orient", str(tmp_path / "metres.glb"), str(tmp_path / "out.stl")])
    assert stop.value.code == 2 and not (tmp_path / "out.stl").exists()
    with pytest.raises(SystemExit) as stop:
        main(["orient", str(BOX_STEP), str(tmp_path / "out.3mf")])
    assert stop.value.code == 2 and not list(tmp_path.glob("*out*"))


def test_rotations_are_about_fixed_axes_x_then_y():
    box = trimesh.creation.box([10, 20, 30])
    placed = parts.onto_bed(box, x=90, y=90)
    assert np.allclose(placed.extents, [20, 30, 10])  # y first would give [30, 10, 20]
    assert np.allclose(placed.bounds[0], 0)


def test_positive_angles_follow_the_right_hand_rule():
    # +90 about x turns +z towards -y: the cap, on top before, ends up at low y.
    for degrees, cap_low in ((90, True), (-90, False)):
        placed = parts.onto_bed(mushroom(), x=degrees)
        assert (placed.center_mass[1] < placed.extents[1] / 2) == cap_low


def test_the_six_sides_are_all_different():
    downs = [parts.side_down(x, y) for x, y in parts.SIDES]
    assert downs == ["-z", "-y", "+z", "+y", "+x", "-x"]


def test_compare_sides_finds_the_overhang():
    result = parts.compare_sides(mushroom())
    assert result["watertight"] and result["bodies"] == 1
    sides = {s["down"]: s for s in result["sides"]}
    upright, upside_down = sides["-z"], sides["+z"]
    assert upright["bed_contact_mm2"] == pytest.approx(100)  # the stem's foot
    assert upright["overhang_below_45deg_mm2"] == pytest.approx(800)  # cap minus stem
    assert upside_down["bed_contact_mm2"] == pytest.approx(900)  # the cap's top
    assert upside_down["overhang_below_45deg_mm2"] == 0
    assert upright["height_mm"] == upside_down["height_mm"] == 25


def test_orient_writes_a_checked_rotated_solid(tmp_path, capsys):
    out = tmp_path / "box.stl"
    assert main(["orient", str(BOX_STEP), str(out), "--rotate-x", "90"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["one_body"] and report["file"] == str(out)
    assert (report["rotate_x"], report["rotate_y"], report["rotate_z"]) == (90, 0, 0)
    stl = trimesh.load(out, force="mesh")
    assert np.allclose(stl.extents, [10, 30, 20], atol=1e-4)
    assert np.allclose(stl.bounds[0], 0, atol=1e-6)
    assert report["bed_contact_mm2"] == pytest.approx(300, abs=0.01)
    assert [p.name for p in tmp_path.iterdir()] == ["box.stl"]  # no partial file left


def test_orient_also_rotates_an_stl(tmp_path, capsys):
    trimesh.creation.box([10, 20, 30]).export(tmp_path / "in.stl")
    assert main(["orient", str(tmp_path / "in.stl"), str(tmp_path / "out.stl"),
                 "--rotate-y", "90"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert np.allclose(trimesh.load(tmp_path / "out.stl", force="mesh").extents, [30, 20, 10])


def test_failed_orient_leaves_the_target_alone(tmp_path, capsys):
    two_boxes().export(tmp_path / "two.stl")
    target = tmp_path / "target.stl"
    trimesh.creation.box([5, 5, 5]).export(target)
    before = target.read_bytes()
    assert main(["orient", str(tmp_path / "two.stl"), str(target)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["ok"] and not report["one_body"] and report["file"] is None
    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["target.stl", "two.stl"]


def test_orientations_reads_step_and_stl_and_flags_non_solids(tmp_path, capsys):
    assert main(["orientations", str(BOX_STEP)]) == 0
    from_step = json.loads(capsys.readouterr().out)
    trimesh.creation.box([10, 20, 30]).export(tmp_path / "box.stl")
    assert main(["orientations", str(tmp_path / "box.stl")]) == 0
    from_stl = json.loads(capsys.readouterr().out)
    key = ("down", "rotate_x", "rotate_y", "height_mm")
    assert [[s[k] for k in key] for s in from_step["sides"]] == \
        [[s[k] for k in key] for s in from_stl["sides"]]
    two_boxes().export(tmp_path / "two.stl")
    assert main(["orientations", str(tmp_path / "two.stl")]) == 1
    assert json.loads(capsys.readouterr().out)["bodies"] == 2
