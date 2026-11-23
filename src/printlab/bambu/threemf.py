"""Read and edit Bambu Studio 3MF projects: settings, plate metadata and meshes."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02",
      "p": "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"}
PROJECT = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
SLICE_INFO = "Metadata/slice_info.config"

for prefix, uri in [("", NS["m"]), ("p", NS["p"]),
                    ("BambuStudio", "http://schemas.bambulab.com/package/2021")]:
    ET.register_namespace(prefix, uri)


def read(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def write(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)


def rewrite(src: Path, dst: Path, edits: dict[str, Callable[[bytes], bytes]]) -> None:
    """Copy a 3MF, passing the named members through their edit functions."""
    members = read(src)
    missing = set(edits) - set(members)
    if missing:
        raise KeyError(f"{src.name} has no {sorted(missing)}")
    write(dst, {n: edits[n](b) if n in edits else b for n, b in members.items()})


def xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def set_metadata(parent: ET.Element, key: str, value: str) -> None:
    el = parent.find(f"metadata[@key='{key}']")
    if el is None:
        el = ET.SubElement(parent, "metadata", {"key": key})
    el.set("value", value)


def get_metadata(parent: ET.Element) -> dict[str, str]:
    return {m.get("key"): m.get("value") for m in parent.findall("metadata") if m.get("key")}


def _transform(text: str | None) -> np.ndarray:
    """A 3MF transform as a 4x3 matrix applied to row vectors: p' = p @ M[:3] + M[3]."""
    if not text:
        return np.vstack([np.eye(3), np.zeros(3)])
    return np.array(text.split(), float).reshape(4, 3)


def _apply(m: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    return vertices @ m[:3] + m[3]


def _mesh(root: ET.Element, object_id: str) -> tuple[np.ndarray, np.ndarray]:
    obj = root.find(f"m:resources/m:object[@id='{object_id}']", NS)
    vertices = np.array([[float(v.get(c)) for c in "xyz"]
                         for v in obj.findall("m:mesh/m:vertices/m:vertex", NS)])
    triangles = np.array([[int(t.get(c)) for c in ("v1", "v2", "v3")]
                          for t in obj.findall("m:mesh/m:triangles/m:triangle", NS)])
    return vertices, triangles


def objects(members: dict[str, bytes]) -> list[dict]:
    """Every build item: its name, extruder setting and mesh in plate coordinates.

    ``parts`` holds one entry per component, with the part's name and extruder
    from model_settings (falling back to the object's): ``object`` is the mesh
    in the object's own frame (component transform applied), ``plate`` the
    same mesh placed on the plate.
    """
    root = ET.fromstring(members["3D/3dmodel.model"])
    settings = ET.fromstring(members[MODEL_SETTINGS])
    out = []
    for item in root.findall("m:build/m:item", NS):
        oid = item.get("objectid")
        obj_settings = settings.find(f"object[@id='{oid}']")
        meta = get_metadata(obj_settings)
        placement = _transform(item.get("transform"))
        parts = []
        for comp in root.findall(f"m:resources/m:object[@id='{oid}']/m:components/m:component", NS):
            path = comp.get(f"{{{NS['p']}}}path").lstrip("/")
            vertices, triangles = _mesh(ET.fromstring(members[path]), comp.get("objectid"))
            local = _apply(_transform(comp.get("transform")), vertices)
            part_el = obj_settings.find(f"part[@id='{comp.get('objectid')}']")
            part_meta = get_metadata(part_el) if part_el is not None else {}
            parts.append({"name": part_meta.get("name", meta.get("name")),
                          "extruder": part_meta.get("extruder", meta.get("extruder")),
                          "object": local, "plate": _apply(placement, local),
                          "triangles": triangles})
        out.append({"id": oid, "name": meta.get("name"), "extruder": meta.get("extruder"),
                    "parts": parts})
    return out


def _canonical(faces: np.ndarray) -> np.ndarray:
    """Triangles rotated so the smallest index comes first (winding kept), rows sorted."""
    f = np.asarray(faces)
    r = np.argmin(f, axis=1)
    out = np.stack([f[np.arange(len(f)), (r + k) % 3] for k in range(3)], axis=1)
    return out[np.lexsort(out.T[::-1])]


def check_mesh(vertices: np.ndarray, triangles: np.ndarray, stl_vertices: np.ndarray,
               stl_faces: np.ndarray, tol_mm: float = 1e-4) -> float:
    """A project mesh equals its STL up to a translation: same vertices, same triangles
    with the same winding. Returns the largest vertex deviation in mm.

    Bambu Studio keeps the STL's vertex order, so that pairing is tried first: the
    nearest STL vertex is ambiguous where two lie closer than the 3MF's coordinates
    are rounded (about 1 µm). A renumbered copy is paired by nearest vertex.

    From cr-lab experiments/007 checks.py.
    """
    vertices = np.asarray(vertices) - np.min(vertices, axis=0)
    stl_vertices = np.asarray(stl_vertices) - np.min(stl_vertices, axis=0)
    d, nearest = cKDTree(stl_vertices).query(vertices)
    worst = float(d.max())
    assert worst < tol_mm, ("vertices without a match in the STL (mm)", worst)
    assert len(triangles) == len(stl_faces), ("triangle count", len(triangles), len(stl_faces))
    pairings = [(nearest, worst)]
    if len(vertices) == len(stl_vertices):
        in_order = float(np.linalg.norm(vertices - stl_vertices, axis=1).max())
        if in_order < tol_mm:
            pairings.insert(0, (np.arange(len(vertices)), in_order))
    expected = _canonical(stl_faces)
    for idx, deviation in pairings:
        if np.array_equal(_canonical(idx[np.asarray(triangles)]), expected):
            return deviation
    raise AssertionError("triangles differ from the STL")


def project_settings(members: dict[str, bytes]) -> dict:
    return json.loads(members[PROJECT])
