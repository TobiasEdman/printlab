"""Bambu Studio vendor profiles, flattened to standalone JSON for the command line.

profiles/bambu/profiles.json names the vendor profiles and the Bambu Studio
version they come from. ``prepare`` resolves each profile's inherits/include
chain and writes profiles/bambu/<key>.json plus the SHA-256 of every vendor file
read. ``check`` fails if the installed app, a vendor file or a committed profile
differs from that record, so a Bambu Studio update cannot silently change what
gets sliced. Design-specific settings are not stored here; they are applied to
each project (see pipeline.py).

Ported from cr-lab experiments 005 and 007 (check_profiles.py, prepare_profiles.py).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from printlab.bambu import studio
from printlab.paths import PROFILES

CONFIG = "profiles.json"
SOURCES = "sources.sha256.json"
# Template keys that describe the template itself, not settings to inherit.
TEMPLATE_KEYS = ("name", "instantiation", "type", "from", "inherits", "include")


def _find(vendor: Path, kind: str, name: str) -> Path:
    matches = list((vendor / kind).rglob(name + ".json"))
    if len(matches) != 1:
        raise ValueError(f"{kind} profile {name!r}: {len(matches)} files in {vendor / kind}")
    return matches[0]


def flatten(vendor: Path, kind: str, name: str, sources: dict | None = None,
            _stack: tuple = ()) -> dict:
    """The profile with its inherits and include chain resolved, nearest value winning.

    Every vendor file read is added to ``sources`` as relative path -> SHA-256.
    """
    if name in _stack:
        raise ValueError(f"inheritance cycle: {' -> '.join(_stack + (name,))}")
    path = _find(vendor, kind, name)
    raw = path.read_bytes()
    if sources is not None:
        sources[str(path.relative_to(vendor))] = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    merged = {}
    if data.get("inherits"):
        merged.update(flatten(vendor, kind, data["inherits"], sources, _stack + (name,)))
    include = data.get("include", [])
    for template in json.loads(include) if isinstance(include, str) else include:
        resolved = flatten(vendor, kind, template, sources, _stack + (name,))
        merged.update({k: v for k, v in resolved.items() if k not in TEMPLATE_KEYS})
    merged.update({k: v for k, v in data.items() if k != "include"})
    merged["inherits"] = ""
    return merged


def load_config(root: Path = PROFILES) -> dict:
    return json.loads((root / CONFIG).read_text())


def prepare(root: Path = PROFILES, vendor: Path | None = None,
            app_version: str | None = None) -> dict:
    """Write every configured profile and the source manifest from the installed app."""
    vendor = vendor or studio.vendor_profiles()
    config = load_config(root)
    sources: dict[str, str] = {}
    for key, entry in config["profiles"].items():
        data = flatten(vendor, entry["kind"], entry["vendor"], sources)
        (root / f"{key}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (root / SOURCES).write_text(json.dumps(dict(sorted(sources.items())), indent=2) + "\n")
    config["bambu_studio"] = app_version or studio.version()
    (root / CONFIG).write_text(json.dumps(config, indent=2) + "\n")
    return {"bambu_studio": config["bambu_studio"], "profiles": sorted(config["profiles"]),
            "vendor_files": len(sources)}


def check(root: Path = PROFILES, vendor: Path | None = None,
          app_version: str | None = None) -> dict:
    """Fail unless the installed app and vendor files still produce the committed profiles."""
    vendor = vendor or studio.vendor_profiles()
    config = load_config(root)
    installed = app_version or studio.version()
    if installed != config["bambu_studio"]:
        raise AssertionError(
            f"Bambu Studio {installed} installed, profiles are from {config['bambu_studio']}; "
            "run `printlab profiles prepare` and review the diff")
    recorded = json.loads((root / SOURCES).read_text())
    changed = [rel for rel, sha in recorded.items()
               if not (vendor / rel).exists()
               or hashlib.sha256((vendor / rel).read_bytes()).hexdigest() != sha]
    if changed:
        raise AssertionError(f"vendor profile files changed: {changed}")
    for key, entry in config["profiles"].items():
        expected = flatten(vendor, entry["kind"], entry["vendor"])
        committed = json.loads((root / f"{key}.json").read_text())
        diff = sorted(k for k in set(expected) | set(committed)
                      if expected.get(k) != committed.get(k))
        if diff:
            raise AssertionError(f"profiles/bambu/{key}.json differs from the vendor chain: {diff}")
    return {"bambu_studio": installed, "vendor_files_sha256_ok": len(recorded),
            "profiles": sorted(config["profiles"])}


def path(key: str, root: Path = PROFILES) -> Path:
    p = root / f"{key}.json"
    if not p.exists():
        known = sorted(load_config(root)["profiles"])
        raise KeyError(f"no profile {key!r} in {root}; known: {known}")
    return p
