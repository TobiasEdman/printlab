# Bambu Studio profiles

Machine, process and filament profiles for the Bambu Lab H2D, flattened by
`printlab profiles prepare` from the vendor profiles that ship with Bambu Studio
02.08.02.61 (`BambuStudio.app/Contents/Resources/profiles/BBL`).
`profiles.json` maps the short names used in `model.yaml` to the vendor profile
names. `sources.sha256.json` records every vendor file they were flattened
from, so `printlab profiles check` refuses an installed Bambu Studio whose
profiles differ.

These files are derived from Bambu Studio, © Bambu Lab, licensed under the GNU
Affero General Public License v3.0 (AGPL-3.0). Source:
<https://github.com/bambulab/BambuStudio>. They stay under that licence; the MIT
licence of the rest of this repository does not apply to them.
