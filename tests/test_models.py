"""Every model.yaml is valid, and library meshes are stored through Git LFS."""

import subprocess

import pytest

from printlab import metadata
from printlab.paths import ROOT

MODELS = metadata.all_models()
LFS_SUFFIXES = {".stl", ".3mf", ".step", ".stp", ".obj", ".zip"}


@pytest.mark.parametrize("model_dir", MODELS, ids=[str(m.relative_to(ROOT)) for m in MODELS])
def test_model_yaml_is_valid(model_dir):
    assert metadata.validate(model_dir, metadata.load(model_dir), metadata.kind(model_dir)) == []


def test_every_model_folder_has_model_yaml():
    for top in metadata.REQUIRED:
        for folder in (ROOT / top).iterdir():
            if folder.is_dir():
                assert (folder / metadata.FILE).exists(), f"{folder.relative_to(ROOT)}"


def test_library_entry_without_licence_or_source_fails(tmp_path):
    (tmp_path / "x.stl").write_text("solid x\nendsolid x\n")
    data = {"name": "x", "description": "d", "author": "a", "files": ["x.stl"]}
    errors = metadata.validate(tmp_path, data, "library")
    assert "missing licence" in errors and "missing source" in errors


def test_slice_section_is_checked(tmp_path):
    data = {"name": "x", "description": "d", "build": "b.py", "outputs": ["a.stl"],
            "slice": {"machine": "h2d-0.4", "process": "0.20-standard", "filaments": ["pla"],
                      "parts": {"a.stl": 2, "b.stl": 1}, "extruders": [3]}}
    (tmp_path / "b.py").write_text("")
    errors = metadata.validate(tmp_path, data, "designs")
    assert "slice: extruders must be 1 (left) or 2 (right)" in errors
    assert "slice: part a.stl: filament slot must be 1..1" in errors
    assert "slice: part b.stl is not in outputs" in errors


def test_slice_variants_need_distinct_outputs(tmp_path):
    (tmp_path / "b.py").write_text("")
    variant = {"machine": "h2d-0.4", "process": "0.20-standard", "filaments": ["abs"],
               "parts": {"a.stl": 1}, "extruders": [1], "assemble": True}
    data = {"name": "x", "description": "d", "build": "b.py", "outputs": ["a.stl"],
            "slice": [{**variant, "output": "x"}, {**variant, "output": "x"}]}
    assert "slice: every variant needs its own output name" in \
        metadata.validate(tmp_path, data, "designs")
    data["slice"][1]["output"] = "X"  # same file as "x" on a case-insensitive disk
    assert "slice: every variant needs its own output name" in \
        metadata.validate(tmp_path, data, "designs")
    data["slice"][1]["output"] = "y"
    assert metadata.validate(tmp_path, data, "designs") == []


def test_slice_variant_edge_cases(tmp_path):
    (tmp_path / "b.py").write_text("")
    base = {"name": "x", "description": "d", "build": "b.py", "outputs": ["a.stl"]}
    assert "slice: the variant list is empty" in \
        metadata.validate(tmp_path, {**base, "slice": []}, "designs")
    variant = {"machine": "h2d-0.4", "process": "0.20-standard", "filaments": ["abs"],
               "parts": {"a.stl": 1}, "extruders": [1]}
    errors = metadata.validate(tmp_path, {**base, "slice": {**variant, "assemble": "no",
                                                            "output": "../x"}}, "designs")
    assert "slice: assemble must be true or false" in errors
    assert "slice: output must be a plain file name (letters, digits, . _ -)" in errors


def test_slice_copies_are_checked(tmp_path):
    (tmp_path / "b.py").write_text("")
    variant = {"machine": "h2d-0.4", "process": "0.20-standard", "filaments": ["pla"],
               "parts": {"a.stl": 1}, "extruders": [1]}
    base = {"name": "x", "description": "d", "build": "b.py", "outputs": ["a.stl"]}
    for bad in (0, "2", True, 1.5):
        assert "slice: copies must be a whole number, at least 1" in \
            metadata.validate(tmp_path, {**base, "slice": {**variant, "copies": bad}}, "designs")
    assembled = {**variant, "copies": 2, "assemble": True}
    assert "slice: copies cannot be combined with assemble" in \
        metadata.validate(tmp_path, {**base, "slice": assembled}, "designs")
    assert metadata.validate(tmp_path, {**base, "slice": {**variant, "copies": 2}},
                             "designs") == []


def test_view_parts_must_be_listed(tmp_path):
    (tmp_path / "b.py").write_text("")
    data = {"name": "x", "description": "d", "build": "b.py", "outputs": ["a.stl"],
            "view": [{"title": "t", "parts": {"z.stl": "#000"}}]}
    assert "view[0]: z.stl is not listed" in metadata.validate(tmp_path, data, "designs")


def test_print_log_entries_are_checked(tmp_path):
    (tmp_path / "b.py").write_text("")
    data = {"name": "x", "description": "d", "build": "b.py", "outputs": ["a.stl"],
            "prints": [{"date": "yesterday", "result": "great"}]}
    errors = metadata.validate(tmp_path, data, "designs")
    assert any("date" in e for e in errors) and any("result" in e for e in errors)
    assert any("filament" in e for e in errors)


def _tracked(paths):
    out = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="not a git checkout")
def test_library_meshes_are_lfs_pointers():
    """The index holds what was committed: an LFS pointer, not the mesh itself."""
    meshes = [p for p in _tracked(["library"]) if p.rsplit(".", 1)[-1].lower()
              in {s[1:] for s in LFS_SUFFIXES}]
    for path in meshes:
        blob = subprocess.run(["git", "cat-file", "blob", f":{path}"], cwd=ROOT,
                              capture_output=True, check=True).stdout
        assert blob.startswith(b"version https://git-lfs.github.com/spec/v1"), \
            f"{path} is committed as a plain blob; install git-lfs and re-add it"
