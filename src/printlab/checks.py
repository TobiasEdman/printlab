"""Geometric print checks on meshes. They do not certify slicing or a physical print.

Ported from cr-lab ``scripts/cr_print_checks.py`` (2026-11-06), keeping the parts
that apply to any printed part.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Error, Manifold, Mesh64
from scipy.spatial import cKDTree

# Ceiling on total enclosed void volume per part, in mm³. Boolean artefacts seen
# in cr-lab stayed below 0.030 mm³; a part that came out hollow must fail even
# though it is still one connected body. Parts with intended voids pass an
# explicit max_void_mm3.
VOID_ALLOWANCE_MM3 = 0.1
# Separate bodies (e.g. inlay pieces) may share faces but not volume.
OVERLAP_TOLERANCE_MM3 = 1e-3


def result_volume(mesh: trimesh.Trimesh | None) -> float:
    """Volume of a Boolean result in mm³; 0 for a missing or empty one.

    trimesh divides by the volume for the centre of mass, so a zero-volume
    contact film warns although the volume it returns (0) is right. Only that
    warning is silenced.
    """
    if mesh is None or len(mesh.faces) == 0:
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return float(mesh.volume)


def support_report(mesh: trimesh.Trimesh) -> dict:
    """Measure overhang surfaces in print orientation (z up, bed at z = 0)."""
    on_bed = mesh.triangles[:, :, 2].max(axis=1) <= 0.05
    down = (mesh.face_normals[:, 2] < -1e-6) & ~on_bed
    angles = np.degrees(np.arccos(np.clip(-mesh.face_normals[down, 2], 0, 1)))
    areas = mesh.area_faces[down]
    shallow = float(areas[angles < 45].sum())
    return dict(
        bed_contact_area_mm2=round(
            float(mesh.area_faces[on_bed & (mesh.face_normals[:, 2] < -0.99)].sum()), 2
        ),
        overhang_area_below_45deg_mm2=round(shallow, 2),
        horizontal_ceiling_area_mm2=round(float(areas[angles < 1].sum()), 2),
        supports_or_bridge_validation_required=shallow > 1,
        slicer_verified=False,
        physical_print_verified=False,
    )


def material_connectivity(mesh: trimesh.Trimesh, *, max_void_mm3: float = VOID_ALLOWANCE_MM3):
    """Require one material region with strictly enclosed, disjoint void shells.

    Every shell is kept. Boundary contact and overlapping or nested negative
    shells are rejected: those are invalid boundary representations, not
    separate voids. ``one_body`` is topology only; ``void_volume_ok`` bounds the
    total void volume separately, and gates must require both.
    """
    clearance = 1e-7  # mm; strict boundary separation, not an assembly allowance

    def solid(boundary):
        if not boundary.is_volume:
            return None
        result = Manifold(Mesh64(
            np.array(boundary.vertices, dtype=np.float64, order="C", copy=True),
            np.array(boundary.faces, dtype=np.uint64, order="C", copy=True),
        ))
        return result if result.status() == Error.NoError else None

    shells = list(mesh.split(only_watertight=False))
    volumes = [float(s.volume) for s in shells]
    positive = [s for s in shells if s.volume > 0]
    negative = [s for s in shells if s.volume < 0]
    outer = solid(positive[0]) if len(positive) == 1 else None
    exterior = None
    if outer is not None and negative:
        bounds = positive[0].bounds
        box = trimesh.creation.box(bounds[1] - bounds[0] + 2.0)
        box.apply_translation(bounds.mean(axis=0))
        exterior = solid(box) - outer
    voids, enclosed = [], []
    for shell in negative:
        void_boundary = shell.copy()
        void_boundary.invert()
        void = solid(void_boundary)
        voids.append(void)
        enclosed.append(bool(
            void is not None and exterior is not None
            and (void - outer).is_empty()
            and void.min_gap(exterior, 2 * clearance) > clearance
        ))
    disjoint = all(v is not None for v in voids)
    if disjoint:
        disjoint = all(
            v.min_gap(w, 2 * clearance) > clearance
            for i, v in enumerate(voids) for w in voids[i + 1:]
        )
    valid = (
        bool(mesh.is_volume)
        and outer is not None
        and all(enclosed)
        and disjoint
        and len(positive) + len(negative) == len(shells)
    )
    void_volume = -sum(v for v in volumes if v < 0)
    return dict(
        one_body=valid,
        material_components=len(positive),
        signed_shell_volumes_mm3=volumes,
        enclosed_voids=len(negative),
        void_volume_mm3=void_volume,
        void_volume_limit_mm3=max_void_mm3,
        void_volume_ok=bool(void_volume <= max_void_mm3),
        void_containment_ok=all(enclosed),
        void_boundaries_disjoint=disjoint,
    )


def export_stl_checked(mesh: trimesh.Trimesh, path: Path, *,
                       max_void_mm3: float = VOID_ALLOWANCE_MM3, bodies: int = 1):
    """Write an STL without repair, reload it and check the solid that was written.

    Returns the reloaded mesh and a report whose ``ok`` requires one body (or
    exactly ``bodies`` separate closed bodies without voids, e.g. inlay pieces),
    the void ceiling, and a vertex round trip within float32 precision.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
    loaded = trimesh.load(path, force="mesh")
    tolerance = 2 * np.finfo(np.float32).eps * max(1.0, np.abs(mesh.vertices).max())
    distance = max(
        float(cKDTree(mesh.vertices).query(loaded.vertices)[0].max()),
        float(cKDTree(loaded.vertices).query(mesh.vertices)[0].max()),
    )
    connectivity = material_connectivity(loaded, max_void_mm3=max_void_mm3)
    overlap = None
    if bodies == 1:
        shape_ok = connectivity["one_body"] and connectivity["void_volume_ok"]
    else:
        # Counting shells is not enough: overlapping pieces are separate shells
        # too. Their union must keep the summed volume.
        pieces = list(loaded.split(only_watertight=False))
        merged = trimesh.boolean.union(pieces, engine="manifold") if len(pieces) > 1 else loaded
        overlap = float(sum(p.volume for p in pieces) - result_volume(merged))
        shape_ok = (loaded.is_volume and connectivity["enclosed_voids"] == 0
                    and connectivity["material_components"] == bodies
                    and overlap <= OVERLAP_TOLERANCE_MM3)
    ok = bool(shape_ok and distance <= tolerance)
    return loaded, dict(
        file=path.name,
        watertight=bool(loaded.is_watertight),
        one_body=connectivity["one_body"],
        connectivity=connectivity,
        positive_volume=bool(loaded.is_volume),
        volume_mm3=round(result_volume(loaded), 3),
        bodies_overlap_mm3=overlap,
        max_vertex_roundtrip_mm=distance,
        float32_tolerance_mm=tolerance,
        ok=ok,
    )
