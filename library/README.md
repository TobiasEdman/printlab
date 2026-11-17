# Library

Models from elsewhere: downloads, files from colleagues, purchased models. Each
lives in `library/<slug>/` with its files and a `model.yaml`.

## Adding a model

1. `mkdir library/<slug>` and copy the files in. Meshes (STL, 3MF, STEP, OBJ,
   ZIP) are stored through Git LFS; run `git lfs install` once per machine.
2. Write `model.yaml`:

   ```yaml
   name: Cable clip
   description: What it is and how it is meant to be printed.
   source: https://www.printables.com/model/...   # or 'unknown'
   author: creator's name or handle                # or 'unknown'
   licence: CC-BY-NC-4.0                           # SPDX id, or LicenseRef-<name>
   files: [cable_clip.stl]
   added: 2026-11-06
   prints: []
   ```

3. `uv run pytest tests/test_models.py -q` checks the entry and that the meshes
   went into LFS.

Keep the creator's licence exactly as published. This repository is public:
add only models whose licence allows redistribution, never "Standard Digital
File License", ND or personal-use terms. Keep those in a private fork.

A `slice` section (same schema as designs, parts taken from `files`) lets
`printlab slice` handle single-part STLs. Multi-part models that must stay
assembled are better printed from their 3MF in Bambu Studio.
