"""printlab used from another repository: explicit paths, no model.yaml or build/."""

import importlib
import json
import re
import shutil
import subprocess
import zipfile

import pytest
import trimesh

from printlab import paths, viewer
from printlab.paths import ROOT


def test_write_all_outside_the_repo(tmp_path):
    source = tmp_path / "experiments" / "005"
    source.mkdir(parents=True)
    trimesh.creation.box([10, 10, 4]).export(source / "body.stl")
    out = tmp_path / "outputs" / "3d"
    written = viewer.write_all("Buoy", [{"title": "Body", "parts": {"body.stl": "#00AE42"}}],
                               source=source, out_dir=out, prefix="buoy")
    assert [p.name for p in written] == ["viewer.html", "buoy_body.glb"]
    assert all(p.parent == out for p in written)
    html = written[0].read_text()
    scenes = json.loads(re.search(r"const SCENES = (.*);\n", html).group(1))
    assert scenes[0]["title"] == "Body" and scenes[0]["parts"][0]["name"] == "body.stl"
    assert written[1].read_bytes()[:4] == b"glTF"


def test_part_names_in_page_are_file_names(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    trimesh.creation.box([1, 1, 1]).export(tmp_path / "a" / "b" / "p.stl")
    page = viewer.write_page("t", [{"title": "s", "parts": {"a/b/p.stl": "#000"}}],
                             tmp_path, tmp_path / "v.html")
    assert '"name": "p.stl"' in page.read_text()


def test_root_follows_printlab_root(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINTLAB_ROOT", str(tmp_path))
    try:
        assert importlib.reload(paths).ROOT == tmp_path.resolve()
    finally:
        monkeypatch.delenv("PRINTLAB_ROOT")
        importlib.reload(paths)
    assert paths.ROOT == ROOT  # back to this checkout


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build the wheel")
def test_wheel_ships_the_viewer_template(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
                   check=True, capture_output=True)
    (wheel,) = tmp_path.glob("printlab-*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "printlab/viewer_template.html" in names and "printlab/bambu/pipeline.py" in names
