import json

import pytest

from printlab.bambu import profiles


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture
def vendor(tmp_path):
    v = tmp_path / "BBL"
    put(v / "machine/base.json", {"name": "base", "type": "machine", "speed": "1", "depth": "a"})
    put(v / "machine/tpl.json", {"name": "tpl", "type": "machine", "instantiation": "false",
                                 "start_gcode": "G28"})
    put(v / "machine/printer.json", {"name": "printer", "type": "machine", "from": "system",
                                     "inherits": "base", "include": ["tpl"], "speed": "2"})
    return v


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "profiles"
    put(r / "profiles.json", {"bambu_studio": "x", "profiles": {
        "m": {"kind": "machine", "vendor": "printer"}}})
    return r


def test_flatten_resolves_inherits_and_include(vendor):
    sources = {}
    d = profiles.flatten(vendor, "machine", "printer", sources)
    assert d["speed"] == "2" and d["depth"] == "a" and d["start_gcode"] == "G28"
    assert d["name"] == "printer" and d["inherits"] == "" and "include" not in d
    assert "instantiation" not in d  # template-only key does not leak
    assert set(sources) == {"machine/printer.json", "machine/base.json", "machine/tpl.json"}


def test_cycle_is_rejected(tmp_path):
    v = tmp_path / "BBL"
    put(v / "machine/a.json", {"name": "a", "inherits": "b"})
    put(v / "machine/b.json", {"name": "b", "inherits": "a"})
    with pytest.raises(ValueError, match="cycle"):
        profiles.flatten(v, "machine", "a")


def test_check_passes_after_prepare(vendor, root):
    profiles.prepare(root, vendor, app_version="1.0")
    assert profiles.check(root, vendor, app_version="1.0")["vendor_files_sha256_ok"] == 3


def test_check_fails_on_other_app_version(vendor, root):
    profiles.prepare(root, vendor, app_version="1.0")
    with pytest.raises(AssertionError, match="installed"):
        profiles.check(root, vendor, app_version="1.1")


def test_check_fails_when_vendor_file_changes(vendor, root):
    profiles.prepare(root, vendor, app_version="1.0")
    put(vendor / "machine/base.json", {"name": "base", "speed": "1", "depth": "b"})
    with pytest.raises(AssertionError, match="vendor profile files changed"):
        profiles.check(root, vendor, app_version="1.0")


def test_check_fails_when_committed_profile_is_edited(vendor, root):
    profiles.prepare(root, vendor, app_version="1.0")
    data = json.loads((root / "m.json").read_text())
    data["speed"] = "9"
    (root / "m.json").write_text(json.dumps(data))
    with pytest.raises(AssertionError, match="differs from the vendor chain"):
        profiles.check(root, vendor, app_version="1.0")


def test_committed_profiles_are_flat():
    """The repo's own profiles: no inheritance left for Bambu Studio to resolve."""
    config = profiles.load_config()
    for key in config["profiles"]:
        data = json.loads(profiles.path(key).read_text())
        assert data["inherits"] == "" and "include" not in data, key
