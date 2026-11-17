import base64
import json
import re
import runpy

import trimesh

from printlab import viewer
from printlab.paths import ROOT, build_dir


def scenes(html: str) -> list[dict]:
    return json.loads(re.search(r"const SCENES = (.*);\n", html).group(1))


def test_design_view_embeds_the_built_mesh():
    design = ROOT / "designs/calibration-cube"
    runpy.run_path(str(design / "build.py"), run_name="__main__")
    html = viewer.render(design)[0].read_text()
    assert "__SCENES__" not in html and "__TITLE__" not in html
    (scene,) = scenes(html)
    (part,) = scene["parts"]
    stl = build_dir(design) / "calibration_cube.stl"
    assert scene["title"] == "calibration_cube" and part["name"] == stl.name
    assert base64.b64decode(part["stl"]) == stl.read_bytes()


def test_glb_holds_coloured_parts_at_real_size_y_up(tmp_path):
    base = trimesh.creation.box([88, 25, 3])  # a two-colour tag: navy base, white inlay
    base.apply_translation([44, 12.5, 1.5])
    inlay = trimesh.creation.box([10, 5, 0.6])
    inlay.apply_translation([20, 12.5, 2.7])
    base.export(tmp_path / "tag_base.stl")
    inlay.export(tmp_path / "tag_inlay.stl")
    scene = {"title": "Navy and white",
             "parts": {"tag_base.stl": "#0C2340", "tag_inlay.stl": "#FFFFFF"}}
    written = viewer.write_all("Tag", [scene], source=tmp_path, out_dir=tmp_path / "out",
                               prefix="tag")
    glb = next(p for p in written if p.suffix == ".glb")
    data = glb.read_bytes()
    assert data[:4] == b"glTF" and int.from_bytes(data[8:12], "little") == len(data)
    assert int.from_bytes(data[12:16], "little") % 4 == 0 and data[16:20] == b"JSON"
    assert trimesh.load(glb, force="scene").geometry  # still a loadable GLB after patching
    gltf = json.loads(data[20:20 + int.from_bytes(data[12:16], "little")])
    colours = {m["name"]: m["pbrMetallicRoughness"]["baseColorFactor"] for m in gltf["materials"]}
    assert colours["tag_inlay"] == [1.0, 1.0, 1.0, 1.0]
    # glTF colours are linear: encoding back to sRGB must give the hex exactly.
    srgb = [12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
            for c in colours["tag_base"][:3]]
    assert [round(c * 255) for c in srgb] == [0x0C, 0x23, 0x40]
    assert colours["tag_base"][0] < 0.01  # linear, not hex/255 (0.047)
    accessors = [gltf["accessors"][p["attributes"]["POSITION"]]
                 for m in gltf["meshes"] for p in m["primitives"]]
    lo = [min(a["min"][i] for a in accessors) for i in range(3)]
    hi = [max(a["max"][i] for a in accessors) for i in range(3)]
    extent = [round(h - low, 5) for h, low in zip(hi, lo, strict=True)]
    assert extent == [0.088, 0.003, 0.025]  # metres; thickness on y (glTF is y-up)


def test_view_section_defines_scenes_and_colours(tmp_path):
    data = {"files": ["a.stl", "b.stl"],
            "view": [{"title": "Both", "parts": {"a.stl": "#000", "b.stl": "#fff"}}]}
    view, _ = viewer.scenes_for(ROOT / "library/x", data)
    assert view == data["view"]


def test_default_view_is_one_scene_per_stl():
    data = {"files": ["a.stl", "b.3mf", "c.STL"]}
    view, _ = viewer.scenes_for(ROOT / "library/x", data)
    assert [s["title"] for s in view] == ["a", "c"]
