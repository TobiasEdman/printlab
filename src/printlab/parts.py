"""Parts from elsewhere: STEP import, print orientation and an axis-aligned side comparison.

    printlab orientations part.step             # which side down?
    printlab orient part.step part.stl --rotate-x 90

printlab slices an STL as it lies; nothing re-orients it later. These helpers
turn a STEP (or an STL, taken to be in mm) into one closed solid in mm, rotate it
into its print orientation and put it on the bed, and compare the six
axis-aligned sides by bed contact and overhang so the choice is measured rather
than guessed. Rotations are about the fixed x, y and z axes, applied in that
order; a positive angle turns counter-clockwise seen from the positive axis
(right-hand rule).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from printlab.checks import support_report

STEP_SUFFIXES = (".step", ".stp")
INPUT_SUFFIXES = (*STEP_SUFFIXES, ".stl")
TOL_LINEAR_MM = 0.01   # chord deviation of the STEP tessellation
TOL_ANGULAR_RAD = 0.1  # cascadio's default 0.5 leaves small holes coarse
# Rotations (about x, then y, in degrees) that put each axis-aligned side down.
SIDES = ((0, 0), (90, 0), (180, 0), (270, 0), (0, 90), (0, 270))


def load_step(path: str | Path, tol_linear_mm: float = TOL_LINEAR_MM,
              tol_angular_rad: float = TOL_ANGULAR_RAD) -> trimesh.Trimesh:
    """A STEP file as one mesh in mm, units taken from the file.

    cascadio (OpenCASCADE) writes metres with separate vertices for each CAD
    face; merging the vertices joins them into closed shells.
    """
    scene = trimesh.load(path, tol_linear=tol_linear_mm, tol_angular=tol_angular_rad)
    mesh = scene.convert_units("millimeters").to_geometry()
    mesh.merge_vertices(digits_vertex=4)  # 0.1 µm
    return mesh


def load(path: str | Path) -> trimesh.Trimesh:
    """A STEP through load_step, or an STL in mm. Other formats carry their own
    units or several objects, so they are refused rather than guessed."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in INPUT_SUFFIXES:
        raise ValueError(f"{path.name}: expected one of {', '.join(INPUT_SUFFIXES)}")
    if suffix in STEP_SUFFIXES:
        return load_step(path)
    return trimesh.load(path, force="mesh")


def rotation(x: float = 0, y: float = 0, z: float = 0) -> np.ndarray:
    """4x4 rotation about the fixed x, then y, then z axes, in degrees."""
    return trimesh.transformations.euler_matrix(*np.radians([x, y, z]), "sxyz")


def onto_bed(mesh: trimesh.Trimesh, x: float = 0, y: float = 0,
             z: float = 0) -> trimesh.Trimesh:
    """A copy rotated by rotation(x, y, z), with its lowest corner at the origin."""
    mesh = mesh.copy()
    mesh.apply_transform(rotation(x, y, z))
    mesh.apply_translation(-mesh.bounds[0])
    return mesh


def side_down(x: float, y: float) -> str:
    """Which side of the original part faces the bed after rotation(x, y), e.g. '-z'."""
    down = rotation(x, y)[:3, :3].T @ [0, 0, -1]
    axis = int(np.argmax(np.abs(down)))
    return f"{'+' if down[axis] > 0 else '-'}{'xyz'[axis]}"


def compare_sides(mesh: trimesh.Trimesh) -> dict:
    """Whether the mesh is one closed solid, and bed contact and overhang for each
    axis-aligned side down.

    Large bed contact and little overhang print easiest; a load-bearing part may
    still need its layers along the load. The choice stays with a person.
    """
    sides = []
    for x, y in SIDES:
        placed = onto_bed(mesh, x, y)
        report = support_report(placed)
        sides.append({
            "down": side_down(x, y),
            "rotate_x": x,
            "rotate_y": y,
            "height_mm": round(float(placed.extents[2]), 2),
            "bed_contact_mm2": report["bed_contact_area_mm2"],
            "overhang_below_45deg_mm2": report["overhang_area_below_45deg_mm2"],
        })
    return {"watertight": bool(mesh.is_watertight),
            "bodies": len(mesh.split(only_watertight=False)), "sides": sides}
