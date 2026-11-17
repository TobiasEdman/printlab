"""20 mm calibration cube with a Ø6 mm vertical through-hole.

After printing, measure the outside (expect 20.00 mm) and the hole (expect
6.00 mm): the first shows the printer's XY accuracy, the second how much holes
shrink. Writes build/designs/calibration-cube/calibration_cube.stl.

    uv run python designs/calibration-cube/build.py
"""

import json

import trimesh

from printlab import csg
from printlab.checks import export_stl_checked, support_report
from printlab.paths import build_dir

SIZE_MM = 20.0
HOLE_DIAMETER_MM = 6.0


def make() -> trimesh.Trimesh:
    cube = trimesh.creation.box([SIZE_MM] * 3)
    cube.apply_translation([0, 0, SIZE_MM / 2])
    hole = trimesh.creation.cylinder(radius=HOLE_DIAMETER_MM / 2, height=SIZE_MM + 2, sections=128)
    hole.apply_translation([0, 0, SIZE_MM / 2])
    return csg.difference([cube, hole])


if __name__ == "__main__":
    mesh, report = export_stl_checked(make(), build_dir(__file__) / "calibration_cube.stl")
    assert report["ok"], report
    report["supports"] = support_report(mesh)
    print(json.dumps(report, indent=2))
