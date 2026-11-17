import trimesh

from printlab import csg
from printlab.checks import export_stl_checked, material_connectivity, support_report


def box(size, center=(0, 0, 0)):
    m = trimesh.creation.box([size] * 3)
    m.apply_translation(center)
    return m


def test_solid_box_is_one_body():
    report = material_connectivity(box(10))
    assert report["one_body"] and report["void_volume_ok"] and report["enclosed_voids"] == 0


def test_enclosed_cavity_is_counted_and_exceeds_default_allowance():
    hollow = csg.difference([box(10), box(4)])
    report = material_connectivity(hollow)
    assert report["one_body"] and report["enclosed_voids"] == 1
    assert abs(report["void_volume_mm3"] - 64) < 1e-6
    assert not report["void_volume_ok"]
    assert material_connectivity(hollow, max_void_mm3=65)["void_volume_ok"]


def test_two_separate_bodies_fail():
    report = material_connectivity(csg.union([box(5), box(5, (20, 0, 0))]))
    assert not report["one_body"] and report["material_components"] == 2


def test_export_round_trip(tmp_path):
    loaded, report = export_stl_checked(box(10, (0, 0, 5)), tmp_path / "box.stl")
    assert report["ok"] and report["watertight"]
    assert abs(report["volume_mm3"] - 1000) < 1e-3
    assert support_report(loaded)["overhang_area_below_45deg_mm2"] == 0


def test_export_rejects_hollow_part(tmp_path):
    _, report = export_stl_checked(csg.difference([box(10), box(4)]), tmp_path / "h.stl")
    assert not report["ok"]


def test_export_with_expected_number_of_bodies(tmp_path):
    pieces = trimesh.util.concatenate([box(2, (0, 0, 1)), box(2, (5, 0, 1))])
    assert not export_stl_checked(pieces, tmp_path / "p.stl")[1]["ok"]  # default: one body
    assert export_stl_checked(pieces, tmp_path / "p.stl", bodies=2)[1]["ok"]
    assert not export_stl_checked(pieces, tmp_path / "p.stl", bodies=3)[1]["ok"]


def test_export_rejects_overlapping_bodies(tmp_path):
    # Two 2 mm boxes overlapping by 1 mm: two shells, but not separate pieces.
    pieces = trimesh.util.concatenate([box(2, (0, 0, 1)), box(2, (1, 0, 1))])
    _, report = export_stl_checked(pieces, tmp_path / "o.stl", bodies=2)
    assert not report["ok"] and abs(report["bodies_overlap_mm3"] - 4.0) < 1e-6


def test_floating_ceiling_needs_support():
    # A bridge: two pillars and a slab whose underside faces the bed.
    t = csg.union([box(4, (-8, 0, 2)), box(4, (8, 0, 2)),
                   trimesh.creation.box([20, 4, 2], trimesh.transformations.translation_matrix(
                       [0, 0, 5]))])
    assert support_report(t)["supports_or_bridge_validation_required"]
