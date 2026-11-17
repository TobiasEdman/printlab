"""Build and slice designs through the real Bambu Studio.

Runs only where the pinned Bambu Studio is installed (not in CI); ~10 s.
"""

import json
import runpy

import pytest

from printlab.bambu import pipeline, profiles, studio
from printlab.paths import ROOT

pinned = profiles.load_config()["bambu_studio"]
available = studio.installed() and studio.version() == pinned
pytestmark = [pytest.mark.bambu,
              pytest.mark.skipif(not available, reason=f"needs Bambu Studio {pinned}")]


def test_calibration_cube_slices_as_configured():
    design = ROOT / "designs/calibration-cube"
    runpy.run_path(str(design / "build.py"), run_name="__main__")
    (report,) = pipeline.run(design)
    assert report["status"].startswith("PASS") and not report["assembled"]
    (part,) = report["geometry"]
    assert part["mesh_unchanged"] and part["extruder"] == 2
    assert part["plate_bounds_mm"][0][2] == 0.0
    assert report["settings_applied"] == {"curr_bed_type": "Textured PEI Plate"}
    assert not report["support_used"] and not report["physical_print_verified"]
    assert 0 < report["estimated_grams"] < 9.2  # below a solid 20 mm PLA cube
    saved = json.loads((ROOT / "build/designs/calibration-cube/calibration-cube.slice-report.json")
                       .read_text())
    assert saved["sha256"] == report["sha256"]

