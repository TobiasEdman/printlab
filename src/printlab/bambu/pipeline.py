"""Slice a design or library model headless with Bambu Studio and verify the result.

    uv run printlab slice designs/<slug>

The slice section is one variant or a list of them (e.g. one per material). For
each variant, all under build/<model path>/slice/<output>/:
  0. The installed Bambu Studio and its vendor profiles match profiles/bambu/.
  1. arrange: the parts on one plate, each with its filament slot. With
     ``assemble: true`` the STLs become one object with one part each, keeping
     their relative placement (multi-colour inlays). With ``copies: n`` every
     STL is placed n times, each copy its own object (--clone-objects).
  2. configure: standard nozzles, filament slot -> extruder, the model's settings.
  3. slice, with the slicer's toolpath conflict check.
  4. verify and package: slicer success, meshes unchanged against the STLs (and
     not moved relative to each other when assembled), every object on the bed
     and clear of the others, every part inside its extruder's area, the
     settings as asked, G-code checksum. The packaged 3MF gets printer_model_id,
     which the CLI leaves empty.
Writes build/<model path>/<output>.3mf and <output>.slice-report.json. A passing
report means the project slices as configured; it says nothing about a physical
print.

Ported from cr-lab experiments 005 (slice.sh, verify_and_package.py) and 007
(configure_stand.py, verify_stand.py).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

from printlab import metadata
from printlab.bambu import profiles, studio, threemf
from printlab.paths import ROOT, build_dir

SUCCESS = "return_code=0, error_message=Success."
CONFLICT_CHECK = "gcode path conflicts check takes"


def _string(value):
    """Project settings hold strings or lists of strings."""
    return [str(v) for v in value] if isinstance(value, list) else str(value)


def apply_settings(project: dict, settings: dict) -> dict:
    """Set the model's overrides on a project. Keys must already exist (typos fail);
    a scalar given for a per-filament/per-extruder list is broadcast to its length."""
    applied = {}
    for key, value in settings.items():
        if key not in project:
            raise KeyError(f"unknown Bambu setting {key!r}")
        value = _string(value)
        if isinstance(project[key], list) and not isinstance(value, list):
            value = [value] * len(project[key])
        if isinstance(project[key], list) != isinstance(value, list):
            raise TypeError(f"setting {key!r} is a {type(project[key]).__name__} in the project")
        project[key] = applied[key] = value
    return applied


def _size_per_filament(project: dict, filaments: int, nozzles: int) -> None:
    """Give the per-filament lists the sizes the slicer checks.

    With several filaments the CLI's arranged project keeps a flush matrix that
    is not n x n per nozzle (a 4 x 4 one for two ABS filaments), one
    flush_multiplier and one filament_colour, and the G-code export then fails
    with "Flush volumes matrix do not match to the correct size!" (2026-11-06).
    The slicer wants an n x n matrix per nozzle (zero diagonal) and one
    multiplier per nozzle, as in cr-lab's two-filament buoy project. Every
    off-diagonal entry gets the same flush volume, so the matrix order cannot
    matter; with one filament per nozzle no colour change happens in a nozzle.
    """
    matrix = project.get("flush_volumes_matrix", [])
    if len(matrix) != nozzles * filaments * filaments:
        flush = next((v for v in matrix if v != "0"), "280")
        project["flush_volumes_matrix"] = ["0" if i == j else flush for _ in range(nozzles)
                                           for i in range(filaments) for j in range(filaments)]
    multiplier = project.get("flush_multiplier", ["1"])
    if len(multiplier) != nozzles:
        project["flush_multiplier"] = [multiplier[0]] * nozzles
    colours = project.get("filament_colour", ["#FFFFFF"])
    if len(colours) != filaments:
        project["filament_colour"] = (colours + [colours[-1]] * filaments)[:filaments]


def configure(members: dict[str, bytes], extruders: list[int], settings: dict) -> tuple:
    """Return the configured members and the settings that were applied."""
    project = threemf.project_settings(members)
    nozzles = len(project["nozzle_diameter"])
    _size_per_filament(project, len(extruders), nozzles)
    project.update(extruder_nozzle_count=["1"] * nozzles,
                   extruder_nozzle_stats=["Standard#1"] * nozzles,
                   extruder_nozzle_stats_new=["Standard#1"] * nozzles,
                   extruder_nozzle_volume_type=["Standard"] * nozzles,
                   filament_map=[str(e) for e in extruders],
                   filament_map_mode="Manual")
    applied = apply_settings(project, settings)
    model = ET.fromstring(members[threemf.MODEL_SETTINGS])
    plates = model.findall("plate")
    assert len(plates) == 1, f"expected one plate, got {len(plates)}"
    for key, value in {"filament_map_mode": "Manual",
                       "filament_maps": " ".join(str(e) for e in extruders),
                       "filament_volume_maps": " ".join("0" for _ in extruders)}.items():
        threemf.set_metadata(plates[0], key, value)
    out = dict(members)
    out[threemf.PROJECT] = json.dumps(project, indent=2).encode()
    out[threemf.MODEL_SETTINGS] = threemf.xml_bytes(model)
    return out, applied


def _run(args: list[str], cwd: Path, log: str) -> None:
    with open(cwd / log, "w") as f:
        rc = subprocess.run(args, cwd=cwd, stdout=f, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        raise RuntimeError(f"Bambu Studio exited {rc}; see {cwd / log}")


def _area(machine: dict, extruder: int) -> Polygon:
    corners = machine["extruder_printable_area"][extruder - 1].split(",")
    return Polygon([tuple(float(c) for c in p.split("x")) for p in corners])


def check_placement(objects: list[dict], parts: list[Path], slots: list[int],
                    extruders: list[int], machine: dict, assemble: bool = False,
                    copies: int = 1) -> list[dict]:
    """Every STL appears ``copies`` times, unchanged, with its filament slot, on the
    bed and inside its extruder's area; objects do not overlap; assembled parts
    keep their relative placement.

    ``objects`` is threemf.objects() of the project. Returns one record per part.
    """
    if assemble:  # one object holding every STL as a part, placed as in the STLs
        assert copies == 1, "copies cannot be combined with assemble"
        assert len(objects) == 1 and len(objects[0]["parts"]) == len(parts), \
            [len(o["parts"]) for o in objects]
    else:
        assert len(objects) == len(parts) * copies, (len(objects), len(parts), copies)
        assert all(len(o["parts"]) == 1 for o in objects), "one mesh per STL expected"
    names = [p.name for p in parts]
    found = sorted(part["name"] for obj in objects for part in obj["parts"])
    assert found == sorted(names * copies), \
        f"parts {found} do not match the STLs {sorted(names)} x {copies}"
    footprints = [unary_union([MultiPoint(p["plate"][:, :2]).convex_hull for p in o["parts"]])
                  for o in objects]
    for i, j in itertools.combinations(range(len(objects)), 2):
        assert footprints[i].intersection(footprints[j]).area < 1e-6, \
            f"{objects[i]['name']} and {objects[j]['name']} overlap on the plate"
    geometry, offsets = [], []
    for obj in objects:
        z_min = min(float(part["plate"][:, 2].min()) for part in obj["parts"])
        assert abs(z_min) < 1e-4, f"{obj['name']} is not on the bed (z min {z_min})"
        for part in obj["parts"]:
            name = part["name"]
            index = names.index(name)
            assert part["extruder"] == str(slots[index]), \
                f"{name} has filament slot {part['extruder']}, expected {slots[index]}"
            stl = trimesh.load(parts[index], force="mesh")  # merges vertices, as Bambu does
            deviation = threemf.check_mesh(part["object"], part["triangles"],
                                           stl.vertices, stl.faces)
            offsets.append(part["object"].min(axis=0) - stl.vertices.min(axis=0))
            lo, hi = part["plate"].min(axis=0), part["plate"].max(axis=0)
            extruder = extruders[slots[index] - 1]
            footprint = MultiPoint(part["plate"][:, :2]).convex_hull
            assert _area(machine, extruder).buffer(1e-6).covers(footprint), \
                f"{name} lies outside extruder {extruder}'s printable area"
            geometry.append({"object": obj["name"], "part": name,
                             "filament_slot": slots[index], "extruder": extruder,
                             "mesh_unchanged": True, "max_vertex_deviation_mm": deviation,
                             "plate_bounds_mm": [lo.round(2).tolist(), hi.round(2).tolist()]})
    if assemble:
        spread = float(np.ptp(np.array(offsets), axis=0).max())
        assert spread < 1e-4, f"assembled parts moved relative to each other ({spread} mm)"
    return geometry


def verify(members: dict[str, bytes], log: str, parts: list[Path], slots: list[int],
           extruders: list[int], filaments: list[str], applied: dict, machine: dict,
           assemble: bool = False, copies: int = 1) -> dict:
    assert SUCCESS in log and CONFLICT_CHECK in log, "slicer did not report success"
    project = threemf.project_settings(members)
    assert project["printer_model"] == machine["printer_model"], project["printer_model"]
    assert project["filament_map"] == [str(e) for e in extruders], project["filament_map"]
    for key, value in applied.items():
        assert project[key] == value, (key, project[key], value)
    types = [json.loads(profiles.path(f).read_text())["filament_type"][0] for f in filaments]
    assert project["filament_type"] == types, (project["filament_type"], types)
    geometry = check_placement(threemf.objects(members), parts, slots, extruders, machine,
                               assemble, copies)

    info = ET.fromstring(members[threemf.SLICE_INFO]).find("plate")
    details = threemf.get_metadata(info)
    assert details["outside"] == "false", "part outside the plate"
    # group_id is the 0-based extruder the slicer actually used for the filament
    # (checked 2026-11-06: extruders [1] -> 0, [2] -> 1).
    for f in info.findall("filament"):
        slot = int(f.get("id"))
        assert int(f.get("group_id")) == extruders[slot - 1] - 1, \
            f"filament {slot} sliced on extruder {int(f.get('group_id')) + 1}"
    gcode = members["Metadata/plate_1.gcode"]
    md5 = members["Metadata/plate_1.gcode.md5"].decode().strip().lower()
    assert hashlib.md5(gcode).hexdigest().lower() == md5, "G-code checksum"
    return {
        "geometry": geometry,
        "settings_applied": applied,
        "filament_map": project["filament_map"],
        "support_used": details["support_used"] == "true",
        "estimated_seconds": int(details["prediction"]),
        "estimated_grams": float(details["weight"]),
        "filaments_used": [f.attrib for f in info.findall("filament")],
        "gcode_md5_verified": True,
        "toolpath_conflict_check_completed": True,
    }


def package(members: dict[str, bytes], model_id: str) -> dict[str, bytes]:
    """Fill printer_model_id, the only change made after slicing."""
    root = ET.fromstring(members[threemf.SLICE_INFO])
    el = root.find("plate/metadata[@key='printer_model_id']")
    assert el is not None and el.get("value") in ("", model_id), el.get("value")
    el.set("value", model_id)
    return {**members, threemf.SLICE_INFO: threemf.xml_bytes(root)}


def run(model_dir: Path) -> list[dict]:
    """Slice every variant in the model's slice section; one report per variant."""
    model_dir = Path(model_dir).resolve()
    data = metadata.load(model_dir)
    kind = metadata.kind(model_dir)
    errors = metadata.validate(model_dir, data, kind)
    assert not errors, f"{model_dir.name}/model.yaml: {errors}"
    assert "slice" in data, f"{model_dir.name}/model.yaml has no slice section"
    variants = data["slice"] if isinstance(data["slice"], list) else [data["slice"]]
    profile_check = profiles.check()
    return [_slice(model_dir, kind, cfg, profile_check) for cfg in variants]


def _slice(model_dir: Path, kind: str, cfg: dict, profile_check: dict) -> dict:
    out = build_dir(model_dir)
    source = out if kind == "designs" else model_dir
    names = list(cfg["parts"])
    parts = [source / n for n in names]
    missing = [p.name for p in parts if not p.exists()]
    assert not missing, f"missing {missing}; run the design's build script first"
    slots = [cfg["parts"][n] for n in names]
    extruders, filaments = cfg["extruders"], cfg["filaments"]
    assemble = bool(cfg.get("assemble"))
    copies = cfg.get("copies", 1)
    output = cfg.get("output", model_dir.name)

    work = out / "slice" / output
    work.mkdir(parents=True, exist_ok=True)
    for name in ("arranged.3mf", "configured.3mf", "sliced.3mf"):
        (work / name).unlink(missing_ok=True)
    exe = str(studio.executable())
    settings_arg = f"{profiles.path(cfg['machine'])};{profiles.path(cfg['process'])}"
    arrange = [exe, "--load-settings", settings_arg,
               "--load-filaments", ";".join(str(profiles.path(f)) for f in filaments),
               "--load-filament-ids", ",".join(str(s) for s in slots),
               "--arrange", "1", "--orient", "0", "--outputdir", str(work),
               "--export-3mf", "arranged.3mf"]
    if len(filaments) > 1:
        arrange.append("--allow-multicolor-oneplate")
    if assemble:  # keep the STLs' relative placement: one object, one part per STL
        arrange.append("--assemble")
    if copies > 1:  # each STL n times, every copy its own object
        arrange += ["--clone-objects", ",".join(str(copies) for _ in parts)]
    _run(arrange + [str(p) for p in parts], work, "arrange.log")

    configured, applied = configure(threemf.read(work / "arranged.3mf"), extruders,
                                    cfg.get("settings") or {})
    threemf.write(work / "configured.3mf", configured)
    _run([exe, "--debug", "3", "--arrange", "0", "--orient", "0", "--slice", "1",
          "--outputdir", str(work), "--export-3mf", "sliced.3mf", "configured.3mf"],
         work, "slice.log")

    sliced = threemf.read(work / "sliced.3mf")
    machine = json.loads(profiles.path(cfg["machine"]).read_text())
    checks = verify(sliced, (work / "slice.log").read_text(), parts, slots, extruders,
                    filaments, applied, machine, assemble, copies)
    vendor_model = studio.vendor_profiles() / "machine" / f"{machine['printer_model']}.json"
    model_id = json.loads(vendor_model.read_text())["model_id"]
    target = out / f"{output}.3mf"
    threemf.write(target, package(sliced, model_id))

    report = {
        "status": "PASS: sliced as configured; not a physical print",
        "model": str(model_dir.relative_to(ROOT)),
        "file": str(target.relative_to(ROOT)),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "bambu_studio": profile_check["bambu_studio"],
        "profiles": {"machine": cfg["machine"], "process": cfg["process"],
                     "filaments": filaments},
        "printer_model_id": model_id,
        "assembled": assemble,
        "copies": copies,
        "physical_print_verified": False,
        **checks,
    }
    (out / f"{output}.slice-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
