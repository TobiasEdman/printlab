"""printlab command line.

    printlab profiles check       installed Bambu Studio still matches profiles/bambu/
    printlab profiles prepare     re-flatten the vendor profiles after a Bambu Studio update
    printlab slice <model dir>    slice, verify and package a design or library model
    printlab validate             check every model.yaml
    printlab view <model dir>     write build/<model path>/viewer.html + one GLB per scene
"""

from __future__ import annotations

import argparse
import json
import sys

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
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
