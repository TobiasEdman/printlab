"""printlab command line.

    printlab profiles check       installed Bambu Studio still matches profiles/bambu/
    printlab profiles prepare     re-flatten the vendor profiles after a Bambu Studio update
    printlab slice <model dir>    slice, verify and package a design or library model
    printlab validate             check every model.yaml
    printlab view <model dir>     write build/<model path>/viewer.html + one GLB per scene
    printlab orientations <part>  bed contact and overhang for each axis-aligned side down
    printlab orient <part> <stl> [--rotate-x/-y/-z DEG]
                                  STEP or STL (mm) to one checked solid, rotated, on the bed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from printlab import metadata
from printlab.bambu import pipeline, profiles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="printlab")
    sub = parser.add_subparsers(dest="command", required=True)
    prof = sub.add_parser("profiles", help="Bambu Studio vendor profiles")
    prof.add_argument("action", choices=["check", "prepare"])
    sl = sub.add_parser("slice", help="slice and verify a design or library model")
    sl.add_argument("model_dir")
    sub.add_parser("validate", help="check every model.yaml")
    vw = sub.add_parser("view", help="write a 3D viewer page for a model")
    vw.add_argument("model_dir")
    ori = sub.add_parser("orientations",
                         help="compare the six axis-aligned sides of a STEP or STL (mm)")
    ori.add_argument("part", help="a .step, .stp or .stl file (STL in mm)")
    ori_out = sub.add_parser("orient",
                             help="STEP or STL (mm) to one checked solid, rotated, on the bed")
    ori_out.add_argument("part", help="a .step, .stp or .stl file (STL in mm)")
    ori_out.add_argument("stl", help="output STL; left untouched unless the check passes")
    for axis, order in zip("xyz", ("first", "second", "third"), strict=True):
        ori_out.add_argument(
            f"--rotate-{axis}", type=float, default=0.0, metavar="DEG",
            help=f"degrees about the fixed {axis} axis, applied {order}; "
                 f"positive turns counter-clockwise seen from +{axis}")
    args = parser.parse_args(argv)

    if args.command == "orientations":
        from printlab import parts

        result = parts.compare_sides(_load_part(parser, args.part))
        print(json.dumps(result, indent=2))
        return 0 if result["watertight"] and result["bodies"] == 1 else 1
    if args.command == "orient":
        result = _orient(parser, args)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if args.command == "view":
        from printlab import viewer

        result = {"written": [str(p) for p in viewer.render(args.model_dir)]}
    elif args.command == "profiles":
        result = profiles.check() if args.action == "check" else profiles.prepare()
    elif args.command == "slice":
        result = [{k: r[k] for k in ("status", "file", "estimated_seconds", "estimated_grams",
                                     "sha256")} for r in pipeline.run(args.model_dir)]
    else:
        problems = {str(d): e for d in metadata.all_models()
                    if (e := metadata.validate(d, metadata.load(d), metadata.kind(d)))}
        result = problems or {"valid": [str(d) for d in metadata.all_models()]}
        if problems:
            print(json.dumps(result, indent=2))
            return 1
    print(json.dumps(result, indent=2))
    return 0


def _load_part(parser: argparse.ArgumentParser, path: str):
    from printlab import parts

    try:
        return parts.load(path)
    except ValueError as error:
        parser.error(str(error))


def _orient(parser: argparse.ArgumentParser, args: argparse.Namespace) -> dict:
    """Write the rotated part through a temporary file, so a failed check never
    replaces an existing STL."""
    from printlab import parts
    from printlab.checks import export_stl_checked, support_report

    target = Path(args.stl)
    if target.suffix.lower() != ".stl":
        parser.error(f"{target.name}: the output must be an .stl file")
    mesh = parts.onto_bed(_load_part(parser, args.part), args.rotate_x, args.rotate_y,
                          args.rotate_z)
    partial = target.with_name(f".{target.stem}.partial.stl")
    try:
        written, report = export_stl_checked(mesh, partial)
        if report["ok"]:
            partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    supports = support_report(written)
    return {"ok": report["ok"], "file": str(target) if report["ok"] else None,
            "rotate_x": args.rotate_x, "rotate_y": args.rotate_y, "rotate_z": args.rotate_z,
            "watertight": report["watertight"], "one_body": report["one_body"],
            "volume_mm3": report["volume_mm3"],
            "size_mm": [round(float(v), 2) for v in written.extents],
            "bed_contact_mm2": supports["bed_contact_area_mm2"],
            "overhang_below_45deg_mm2": supports["overhang_area_below_45deg_mm2"]}


if __name__ == "__main__":
    sys.exit(main())
