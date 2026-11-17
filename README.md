# printlab

3D printing as code for the Bambu Lab H2D: parametric designs written in
Python, a library of models from elsewhere with their licences, and a pinned
Bambu Studio pipeline that slices headless and verifies the result.

- **Designs as code.** A design is a `build.py` that builds the part with
  trimesh and manifold3d and exports it through
  `printlab.checks.export_stl_checked`, which reloads the written STL and
  requires one closed solid without voids.
- **Parts from elsewhere.** `printlab orientations` compares the six
  axis-aligned sides of a STEP or STL by bed contact and overhang; `printlab
  orient` turns a STEP (through cascadio, OpenCASCADE) or an STL into one
  checked solid, rotated into print orientation and resting on the bed.
- **Verified slicing.** `printlab slice <model dir>` arranges, configures and
  slices with Bambu Studio's command line, then checks the 3MF: meshes unchanged
  against the STLs, every object on the bed and clear of the others, each part
  inside its nozzle's printable area, the settings as asked, the G-code
  checksum. A passing report means the project slices as configured. It does
  not mean a part printed or fits.
- **Pinned profiles.** `profiles/bambu/` holds H2D vendor profiles flattened
  from one Bambu Studio version. `printlab slice` refuses to run if the
  installed app or its profiles differ.
- **3D viewer.** `printlab view <model dir>` writes a self-contained viewer page
  and one GLB per scene, for sharing a model without a slicer.

## Layout

| Folder | What |
|---|---|
| `designs/<slug>/` | Own designs: `build.py` + `model.yaml` |
| `library/<slug>/` | Models from elsewhere, each under its creator's licence (see [library/README.md](library/README.md)) |
| `profiles/bambu/` | Flattened Bambu Studio profiles (AGPL-3.0, see [its README](profiles/bambu/README.md)) |
| `src/printlab/` | The package: mesh checks, Booleans, viewer, slicing pipeline |
| `build/` | Generated STLs, 3MFs and viewer pages (git-ignored) |

## model.yaml

```yaml
name: Calibration cube
description: 20 mm cube with a 6 mm hole
build: build.py
outputs: [calibration_cube.stl]
slice:
  machine: h2d-0.4
  process: 0.20-standard
  filaments: [pla-basic]            # filament slots 1..n, keys in profiles/bambu/profiles.json
  parts: {calibration_cube.stl: 1}  # part -> filament slot
  extruders: [2]                    # slot -> extruder: 1 left, 2 right
  copies: 1                         # optional: every part n times on the plate
  settings:                         # project overrides on top of the vendor profiles
    curr_bed_type: Textured PEI Plate
prints: []                          # physical prints only: date, filament, result
```

`slice` can also be a list of variants, for example one per material, each with
its own `output`. `assemble: true` keeps several STLs together as one
multi-colour object.

## Printing a part from elsewhere

printlab slices an STL as it lies, so a part from elsewhere needs its print
orientation first.

STEP files carry their own units; STL files are taken to be in mm. Other
formats are refused rather than guessed.

1. **Compare the sides.** `uv run printlab orientations part.step` (or
   `part.stl`) reports whether the part is one closed solid, and for each of
   the six axis-aligned sides down (`down: -z` is the part's own bottom) the
   rotation that gives it, the height, the bed contact and the overhang. Large
   contact and little overhang print easiest; a load-bearing part may need its
   layers along the load instead. Read the designer's notes, then decide.
2. **Convert and orient.**
   `uv run printlab orient part.step library/<slug>/<part>.stl --rotate-x 90`
   writes one closed solid in mm with its lowest corner at the origin.
   Rotations are about the fixed x, then y, then z axes, any angle, and a
   positive angle turns counter-clockwise seen from the positive axis; the
   `rotate_x`/`rotate_y` of an `orientations` row can be passed as they are.
   If the result is not one closed solid, the command exits 1 and leaves the
   output path untouched.
3. **Add a library model:** `library/<slug>/model.yaml` next to the STL.

   ```yaml
   name: <part name>
   description: <what it is and how it lies on the bed>
   source: <URL of the file, or unknown>
   author: <creator, or unknown>
   licence: <SPDX id of the creator's licence>
   files: [<part>.stl]
   slice:
     output: <part>_PLA
     machine: h2d-0.4
     process: 0.20-standard
     filaments: [pla-basic]          # pla-basic, petg-basic, abs or asa
     parts: {<part>.stl: 1}
     extruders: [2]                  # 1 left, 2 right
     copies: 1
     settings:                       # Bambu Studio project keys; unknown keys fail
       curr_bed_type: Textured PEI Plate
       sparse_infill_density: 15%
       enable_support: 1
       support_on_build_plate_only: 1
   prints: []
   ```

4. **Validate and slice:** `uv run printlab validate`, then
   `uv run printlab slice library/<slug>`. The 3MF and its slice report land in
   `build/library/<slug>/`.

## Running

Needs Python 3.11, 3.12 or 3.14 (cascadio has no 3.13 wheels) and
[uv](https://docs.astral.sh/uv/). Slicing needs Bambu Studio 02.08.02.61 on
macOS in `/Applications` (or `BAMBU_STUDIO_APP`); everything else runs anywhere.

```bash
uv sync --extra dev
uv run python designs/calibration-cube/build.py   # -> build/designs/calibration-cube/*.stl
uv run printlab slice designs/calibration-cube    # -> build/.../calibration-cube.3mf + report
uv run printlab view designs/calibration-cube     # -> build/.../viewer.html + .glb
uv run printlab validate                          # checks every model.yaml
uv run pytest -q
```

After a Bambu Studio update: `uv run printlab profiles prepare`, review the
diff, re-slice, commit. Library meshes go through Git LFS: run
`git lfs install` once per machine.

## Using printlab from another repository

```bash
uv add "printlab @ git+https://github.com/TobiasEdman/printlab@<commit>"
```

The library entry points take explicit paths and need no `model.yaml` or
`build/`: `printlab.viewer.write_all` (viewer page + GLBs), `printlab.checks`,
`printlab.csg` and `printlab.parts` (STEP import, rotation onto the bed, side
comparison). Set `PRINTLAB_ROOT` to use the model-based commands
(`slice`, `view`) against another checkout laid out like this one.

## Licence

MIT ([LICENSE](LICENSE)), except `profiles/bambu/`, which is derived from Bambu
Studio and stays under AGPL-3.0. Models under `library/` keep their creators'
licences.

Built on [trimesh](https://github.com/mikedh/trimesh),
[manifold3d](https://github.com/elalish/manifold),
[shapely](https://github.com/shapely/shapely),
[cascadio](https://github.com/trimesh/cascadio) (OpenCASCADE) and
[Bambu Studio](https://github.com/bambulab/BambuStudio).
