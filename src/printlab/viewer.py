"""Shareable 3D views of a model: a three.js page and one GLB file per scene.

    uv run printlab view designs/<slug>
    # -> build/<model path>/viewer.html and <slug>_<scene>.glb

Scenes come from the optional ``view`` section of model.yaml:

    view:
      - title: Two-colour
        parts: {base.stl: "#1b2a4a", logo.stl: "#f4f4f4"}

Without it, every STL of the model gets its own scene. The page embeds the
meshes and needs only three.js from the CDN (template from cr-lab experiment
007). The GLB (binary glTF) holds each part with its colour, centred, in
metres and y-up as glTF requires, so any glTF viewer shows it at real size.

From another repository (no model.yaml or build/ needed):

    from printlab.viewer import write_all
    write_all("Buoy", [{"title": "Body", "parts": {"body.stl": "#00AE42"}}],
              source=Path("experiments/005"), out_dir=Path("outputs/3d"), prefix="buoy")
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

from printlab import metadata
from printlab.paths import build_dir

# Print frame (mm, z up) -> glTF frame (m, y up): x stays, z -> y, y -> -z.
Z_UP_TO_Y_UP = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])

TEMPLATE = Path(__file__).with_name("viewer_template.html")
DEFAULT_COLOUR = "#5a5f66"


def scenes_for(model_dir: Path, data: dict) -> tuple[list[dict], Path]:
    kind = metadata.kind(model_dir)
    source = build_dir(model_dir) if kind == "designs" else Path(model_dir)
    files = data.get("outputs" if kind == "designs" else "files") or []
    stls = [f for f in files if f.lower().endswith(".stl")]
    view = data.get("view") or [{"title": Path(f).stem, "parts": {f: DEFAULT_COLOUR}}
                                for f in stls]
    return view, source


def _linear_rgba(colour: str) -> list[float]:
    """An sRGB hex colour as glTF's baseColorFactor, which is in linear light.

    Writing hex/255 directly makes standard viewers show navy #0C2340 as about
    #3D6889 (found in review, 2026-11-06).
    """
    h = colour.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb] + [1.0]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _set_colours(glb: bytes, colours: dict[str, list[float]]) -> bytes:
    """Write exact baseColorFactor floats into a GLB's JSON chunk.

    trimesh stores colour factors as 8-bit integers, which loses most of the
    precision of dark linear values (navy would come back as #0D2240).
    """
    json_len = int.from_bytes(glb[12:16], "little")
    doc = json.loads(glb[20:20 + json_len])
    for material in doc["materials"]:
        material["pbrMetallicRoughness"]["baseColorFactor"] = colours[material["name"]]
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)  # chunks are 4-byte aligned; JSON pads with spaces
    rest = glb[20 + json_len:]
    total = 12 + 8 + len(text) + len(rest)
    return (glb[:8] + total.to_bytes(4, "little") + len(text).to_bytes(4, "little")
            + b"JSON" + text + rest)


def write_glb(scene: dict, source: Path, out: Path) -> Path:
    """One scene as GLB: a node per part with a matte material in its colour."""
    meshes = {Path(n).stem: trimesh.load(source / n, force="mesh") for n in scene["parts"]}
    centre = trimesh.util.concatenate(list(meshes.values())).bounds.mean(axis=0)
    gltf = trimesh.Scene()
    for (stem, mesh), colour in zip(meshes.items(), scene["parts"].values(), strict=True):
        mesh.apply_translation(-centre)
        mesh.apply_transform(Z_UP_TO_Y_UP)
        mesh.apply_scale(0.001)
        mesh.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name=stem, baseColorFactor=_linear_rgba(colour), metallicFactor=0.0,
            roughnessFactor=0.7))
        gltf.add_geometry(mesh, node_name=stem, geom_name=stem)
    colours = {Path(n).stem: _linear_rgba(c) for n, c in scene["parts"].items()}
    out.write_bytes(_set_colours(gltf.export(file_type="glb"), colours))
    return out


def write_page(title: str, scenes: list[dict], source: Path, out: Path) -> Path:
    """The three.js page: one tab per scene, STLs embedded, parts toggleable.

    ``scenes`` as in model.yaml's ``view``: ``[{"title": ..., "parts": {stl: colour}}]``
    with STL paths relative to ``source``.
    """
    embedded = []
    for scene in scenes:
        parts = []
        for name, colour in scene["parts"].items():
            path = Path(source) / name
            if not path.exists():
                raise FileNotFoundError(f"{path}; build it first")
            parts.append({"name": Path(name).name, "color": colour,
                          "stl": base64.b64encode(path.read_bytes()).decode()})
        embedded.append({"title": scene["title"], "parts": parts})
    html = TEMPLATE.read_text().replace("__TITLE__", title)
    Path(out).write_text(html.replace("__SCENES__", json.dumps(embedded)))
    return Path(out)


def write_all(title: str, scenes: list[dict], source: Path, out_dir: Path,
              prefix: str) -> list[Path]:
    """viewer.html plus <prefix>_<scene>.glb for every scene, in ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    page = write_page(title, scenes, source, out_dir / "viewer.html")
    return [page, *(write_glb(s, Path(source), out_dir / f"{prefix}_{_slug(s['title'])}.glb")
                    for s in scenes)]


def render(model_dir: Path) -> list[Path]:
    """A model's viewer.html and one GLB per scene, in build/; returns their paths."""
    model_dir = Path(model_dir).resolve()
    data = metadata.load(model_dir)
    view, source = scenes_for(model_dir, data)
    return write_all(data.get("name", model_dir.name), view, source, build_dir(model_dir),
                     model_dir.name)
