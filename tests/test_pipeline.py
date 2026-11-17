import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import trimesh

from printlab.bambu import pipeline, threemf

MODEL_SETTINGS = b"""<?xml version="1.0" encoding="UTF-8"?>
<config><object id="2"><metadata key="name" value="a.stl"/></object>
<plate><metadata key="filament_map_mode" value="Auto For Flush"/></plate></config>"""


def members(**project):
    base = {"nozzle_diameter": ["0.4", "0.4"], "curr_bed_type": "Cool Plate",
            "fan_max_speed": ["80"], "sparse_infill_density": "15%"}
    return {threemf.PROJECT: json.dumps({**base, **project}).encode(),
            threemf.MODEL_SETTINGS: MODEL_SETTINGS}


def test_configure_sets_nozzles_extruders_and_settings():
    out, applied = pipeline.configure(members(), [2], {"curr_bed_type": "Textured PEI Plate",
                                                       "fan_max_speed": 50})
    project = json.loads(out[threemf.PROJECT])
    assert project["filament_map"] == ["2"] and project["filament_map_mode"] == "Manual"
    assert project["extruder_nozzle_volume_type"] == ["Standard", "Standard"]
    assert project["curr_bed_type"] == "Textured PEI Plate"
    assert project["fan_max_speed"] == ["50"]  # scalar broadcast to the per-filament list
    assert applied == {"curr_bed_type": "Textured PEI Plate", "fan_max_speed": ["50"]}
    plate = threemf.get_metadata(ET.fromstring(out[threemf.MODEL_SETTINGS]).find("plate"))
    assert plate["filament_map_mode"] == "Manual" and plate["filament_maps"] == "2"


def test_two_filaments_get_matrix_multiplier_and_colours_sized():
    single = members(flush_volumes_matrix=["0", "280", "280", "0"], flush_multiplier=["1"],
                     filament_colour=["#00AE42"])
    out, _ = pipeline.configure(single, [1, 2], {})
    project = json.loads(out[threemf.PROJECT])
    assert project["flush_volumes_matrix"] == ["0", "280", "280", "0"] * 2  # n x n per nozzle
    assert project["flush_multiplier"] == ["1", "1"]
    assert project["filament_colour"] == ["#00AE42", "#00AE42"]
    assert project["filament_map"] == ["1", "2"]


def test_correctly_sized_matrix_is_kept():
    ok = members(flush_volumes_matrix=["0", "150", "810", "0"] * 2, flush_multiplier=["1", "1"],
                 filament_colour=["#000", "#fff"])
    project = json.loads(pipeline.configure(ok, [1, 2], {})[0][threemf.PROJECT])
    assert project["flush_volumes_matrix"] == ["0", "150", "810", "0"] * 2


def test_unknown_setting_is_rejected():
    with pytest.raises(KeyError, match="unknown Bambu setting"):
        pipeline.configure(members(), [1], {"curr_bed_typo": "x"})


def test_list_given_for_scalar_setting_is_rejected():
    with pytest.raises(TypeError):
        pipeline.configure(members(), [1], {"curr_bed_type": ["a", "b"]})


def cube():
    m = trimesh.creation.box([10, 10, 10])
    return np.asarray(m.vertices), np.asarray(m.faces)


def test_check_mesh_accepts_translated_and_renumbered_copy():
    v, f = cube()
    order = np.random.default_rng(0).permutation(len(v))
    inverse = np.argsort(order)
    assert threemf.check_mesh(v[order] + [100, 50, 5], inverse[f], v, f) < 1e-9


def test_check_mesh_rejects_flipped_winding():
    v, f = cube()
    with pytest.raises(AssertionError, match="triangles differ"):
        threemf.check_mesh(v, f[:, ::-1], v, f)


def test_check_mesh_rejects_moved_vertex():
    v, f = cube()
    moved = v.copy()
    moved[0] += [0.01, 0, 0]
    with pytest.raises(AssertionError, match="vertices"):
        threemf.check_mesh(moved, f, v, f)
