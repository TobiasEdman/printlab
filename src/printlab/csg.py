"""Boolean operations through manifold3d, the engine that gives watertight results."""

from __future__ import annotations

import trimesh


def union(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.union(meshes, engine="manifold")


def difference(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    """The first mesh minus all the others."""
    return trimesh.boolean.difference(meshes, engine="manifold")


def intersection(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.intersection(meshes, engine="manifold")
