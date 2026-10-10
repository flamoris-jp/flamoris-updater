"""Bundle entrypoints must not add bytecode even when their directory is writable."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_bundle.py"
spec = importlib.util.spec_from_file_location("build_bundle_launchers", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("entry", list(module.ENTRYPOINTS))
def test_actual_launcher_import_does_not_create_unindexed_cache(tmp_path, entry):
    vendor = tmp_path / "site-packages"
    vendor.mkdir()
    fixture = vendor / "fixture.py"
    fixture.write_text(
        "import json,sys\ndef main():\n"
        "    print(json.dumps({'bytecode':sys.dont_write_bytecode,'args':sys.argv[1:]}))\n"
    )
    scripts = tmp_path / "bin"
    scripts.mkdir()
    executable = scripts / entry
    executable.write_bytes(module.launcher("fixture", "/usr/bin/python3.12"))
    executable.chmod(0o555)
    # Keep the tree writable to reproduce root's ability to bypass sealing.
    result = subprocess.check_output([sys.executable, "-I", str(executable), "--help"])
    assert json.loads(result) == {"bytecode": True, "args": ["--help"]}
    assert not list(vendor.rglob("*.pyc"))
    assert not list(vendor.rglob("__pycache__"))


def test_previous_launcher_writes_cache_when_sealing_does_not_enforce_access(tmp_path):
    vendor = tmp_path / "site-packages"
    vendor.mkdir()
    (vendor / "fixture.py").write_text("def main():\n    pass\n")
    scripts = tmp_path / "bin"
    scripts.mkdir()
    old = scripts / "previous-launcher"
    old.write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'site-packages'))\n"
        "from fixture import main\nmain()\n"
    )
    subprocess.check_call([sys.executable, "-I", str(old)])
    assert list(vendor.rglob("*.pyc"))
