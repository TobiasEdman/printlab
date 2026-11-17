"""Part matching and placement checks on a synthetic Bambu-style 3MF (no Bambu Studio).

The layout copies what Bambu Studio 02.08.02.61 writes for `--assemble`: one
build item, one component per part pointing into a shared object file with
the mesh centred on its bounding box, and model_settings parts whose ids are
the components' object ids.
"""

import numpy as np
import pytest
import trimesh

from printlab.bambu import threemf
from printlab.bambu.pipeline import check_placement

MACHINE = {"extruder_printable_area": ["0x0,325x0,325x320,0x320",
                                       "25x0,350x0,350x320,25x320"]}


def box(lo, hi):
    m = trimesh.creation.box(np.subtract(hi, lo))
    m.apply_translation(np.add(lo, hi) / 2)
    return m


def _mesh_xml(oid, mesh):
    verts = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in mesh.vertices)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces)
    return (f'<object id="{oid}" type="model"><mesh><vertices>{verts}</vertices>'
            f"<triangles>{tris}</triangles></mesh></object>")


def project(meshes, extruders, item=(100, 100, 0), shift=None):
    """3MF members for one assembled object; ``shift`` moves one part's component."""
    core, prod = threemf.NS["m"], threemf.NS["p"]
    objects, comps, parts = [], [], []
    for i, ((name, mesh), extruder) in enumerate(zip(meshes, extruders, strict=True), 1):
        centre = mesh.bounds.mean(axis=0)
        objects.append(_mesh_xml(i, mesh.copy().apply_translation(-centre)))
        t = centre + (np.asarray(shift[1]) if shift and shift[0] == name else 0)
        comps.append(f'<component p:path="/3D/Objects/object_1.model" objectid="{i}" '
                     f'transform="1 0 0 0 1 0 0 0 1 {t[0]} {t[1]} {t[2]}"/>')
        parts.append(f'<part id="{i}"><metadata key="name" value="{name}"/>'
                     f'<metadata key="extruder" value="{extruder}"/></part>')
    model = (f'<model xmlns="{core}" xmlns:p="{prod}"><resources><object id="9" type="model">'
             f'<components>{"".join(comps)}</components></object></resources><build>'
             f'<item objectid="9" transform="1 0 0 0 1 0 0 0 1 {item[0]} {item[1]} {item[2]}"/>'
             f"</build></model>")
    settings = (f'<config><object id="9"><metadata key="name" value="Assembly"/>'
                f'{"".join(parts)}</object></config>')
    return {"3D/3dmodel.model": model.encode(),
            "3D/Objects/object_1.model":
                f'<model xmlns="{core}"><resources>{"".join(objects)}</resources></model>'.encode(),
            threemf.MODEL_SETTINGS: settings.encode()}


def copies(name, mesh, positions):
    """3MF members as --clone-objects writes them: one object and build item per copy,
    each a single component pointing at the same mesh, named <stl>_1, <stl>_2, ..."""
    core, prod = threemf.NS["m"], threemf.NS["p"]
    centre = mesh.bounds.mean(axis=0)
    objects, items, settings = [], [], []
    for i, (x, y) in enumerate(positions, 1):
        objects.append(f'<object id="{10 + i}" type="model"><components><component '
                       f'p:path="/3D/Objects/object_1.model" objectid="1" transform="1 0 0 '
                       f'0 1 0 0 0 1 {centre[0]} {centre[1]} {centre[2]}"/></components></object>')
        items.append(f'<item objectid="{10 + i}" transform="1 0 0 0 1 0 0 0 1 {x} {y} 0"/>')
        settings.append(f'<object id="{10 + i}"><metadata key="name" value="{name}_{i}"/>'
                        f'<metadata key="extruder" value="1"/><part id="1">'
                        f'<metadata key="name" value="{name}"/></part></object>')
    model = (f'<model xmlns="{core}" xmlns:p="{prod}"><resources>{"".join(objects)}'
             f'</resources><build>{"".join(items)}</build></model>')
    mesh_file = _mesh_xml(1, mesh.copy().apply_translation(-centre))
    return {"3D/3dmodel.model": model.encode(),
            "3D/Objects/object_1.model":
                f'<model xmlns="{core}"><resources>{mesh_file}</resources></model>'.encode(),
            threemf.MODEL_SETTINGS: f'<config>{"".join(settings)}</config>'.encode()}


@pytest.fixture
def tag(tmp_path):
    base = box((0, 0, 0), (20, 8, 3))
    inlay = box((4, 2, 0), (16, 6, 0.6))
    paths = []
    for name, mesh in (("base.stl", base), ("inlay.stl", inlay)):
        mesh.export(tmp_path / name)
        paths.append(tmp_path / name)
    return [("base.stl", base), ("inlay.stl", inlay)], paths


def test_objects_reads_part_names_extruders_and_plate_position(tag):
    meshes, _ = tag
    (obj,) = threemf.objects(project(meshes, ["1", "2"]))
    assert [(p["name"], p["extruder"]) for p in obj["parts"]] == [("base.stl", "1"),
                                                                  ("inlay.stl", "2")]
    assert np.allclose(obj["parts"][1]["plate"].min(axis=0), [104, 102, 0])


def test_assembled_parts_in_place_pass(tag):
    meshes, paths = tag
    geometry = check_placement(threemf.objects(project(meshes, ["1", "2"])), paths, [1, 2],
                               [1, 2], MACHINE, assemble=True)
    assert [(g["part"], g["extruder"]) for g in geometry] == [("base.stl", 1), ("inlay.stl", 2)]


def test_moved_part_fails(tag):
    meshes, paths = tag
    objects = threemf.objects(project(meshes, ["1", "2"], shift=("inlay.stl", (0.5, 0, 0))))
    with pytest.raises(AssertionError, match="moved relative"):
        check_placement(objects, paths, [1, 2], [1, 2], MACHINE, assemble=True)


def test_wrong_filament_slot_fails(tag):
    meshes, paths = tag
    with pytest.raises(AssertionError, match="inlay.stl has filament slot 1, expected 2"):
        check_placement(threemf.objects(project(meshes, ["1", "1"])), paths, [1, 2], [1, 2],
                        MACHINE, assemble=True)


def test_stl_matched_twice_fails(tag):
    meshes, paths = tag
    twice = [meshes[0], ("base.stl", meshes[1][1])]
    with pytest.raises(AssertionError, match="do not match the STLs"):
        check_placement(threemf.objects(project(twice, ["1", "2"])), paths, [1, 2], [1, 2],
                        MACHINE, assemble=True)


def test_part_outside_its_extruders_area_fails(tag):
    meshes, paths = tag
    objects = threemf.objects(project(meshes, ["1", "2"], item=(5, 100, 0)))  # x < 25: left only
    with pytest.raises(AssertionError, match="outside extruder 2"):
        check_placement(objects, paths, [1, 2], [1, 2], MACHINE, assemble=True)


def test_copies_each_placed_on_the_bed_pass(tag):
    meshes, paths = tag
    objects = threemf.objects(copies("base.stl", meshes[0][1], [(50, 100), (100, 100)]))
    geometry = check_placement(objects, paths[:1], [1], [1], MACHINE, copies=2)
    assert [(g["object"], g["part"]) for g in geometry] == [("base.stl_1", "base.stl"),
                                                            ("base.stl_2", "base.stl")]


def test_missing_copy_fails(tag):
    meshes, paths = tag
    objects = threemf.objects(copies("base.stl", meshes[0][1], [(50, 100)]))
    with pytest.raises(AssertionError):
        check_placement(objects, paths[:1], [1], [1], MACHINE, copies=2)


def test_overlapping_copies_fail(tag):
    meshes, paths = tag  # the base is 20 mm long: copies 10 mm apart overlap
    objects = threemf.objects(copies("base.stl", meshes[0][1], [(50, 100), (60, 100)]))
    with pytest.raises(AssertionError, match="base.stl_1 and base.stl_2 overlap on the plate"):
        check_placement(objects, paths[:1], [1], [1], MACHINE, copies=2)
