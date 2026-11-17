"""Every design builds and passes the checks its build script asserts."""

import runpy

import pytest

from printlab import metadata
from printlab.paths import build_dir

DESIGNS = [d for d in metadata.all_models() if metadata.kind(d) == "designs"]


@pytest.mark.parametrize("design", DESIGNS, ids=[d.name for d in DESIGNS])
def test_design_builds(design):
    data = metadata.load(design)
    runpy.run_path(str(design / data["build"]), run_name="__main__")
    for name in data["outputs"]:
        assert (build_dir(design) / name).stat().st_size > 0, name

