"""Functional build identity is separate from immutable dev5 release inputs."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "functional_build", ROOT / "scripts/build_trusted_vsi_functional.py")
functional_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(functional_build)


@pytest.mark.parametrize("version", ["0.37.9.dev0", "0.38.0.dev1", "1.0.dev0+local"])
def test_new_functional_development_version(version):
    assert functional_build.functional_version(version) == version


@pytest.mark.parametrize("version", [
    "0.37.8.dev5", "0.37.8.dev6", "0.37.8.dev5+functional", "0.37.7.dev1",
    "0.37.9", "0.38.0rc1", "invalid",
])
def test_functional_build_rejects_release_or_dev5_identity(version):
    with pytest.raises(ValueError):
        functional_build.functional_version(version)


def test_staged_sdist_uses_new_version_without_touching_dev5_checkout(tmp_path):
    import subprocess
    import sys
    import tarfile

    before = {name: (ROOT / name).read_bytes() for name in ("pyproject.toml", "src/c2pa/c2pa.py")}
    stage = tmp_path / "stage"
    stage.mkdir()
    functional_build.stage_source(stage, "0.37.9.dev0")
    assert 'version = "0.37.9.dev0"' in (stage / "pyproject.toml").read_text()
    assert "# Version: 0.37.9.dev0" in (stage / "src/c2pa/c2pa.py").read_text()
    assert not (stage / "src/c2pa/libs").exists()
    subprocess.run([sys.executable, "setup.py", "-q", "sdist", "--dist-dir", str(tmp_path / "dist")],
                   cwd=stage, check=True, capture_output=True)
    (sdist,) = (tmp_path / "dist").iterdir()
    assert sdist.name == "c2pa_python-0.37.9.dev0.tar.gz"
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        info = archive.extractfile("c2pa_python-0.37.9.dev0/PKG-INFO").read().decode()
    assert "Version: 0.37.9.dev0" in info
    for member in ("scripts/build_trusted_vsi_functional.py",
                   "scripts/qualify_trusted_vsi_functional.py",
                   "docs/trusted-vsi-python-contract.md", "src/c2pa/c2pa.py"):
        assert f"c2pa_python-0.37.9.dev0/{member}" in names
    assert not any(name.endswith((".so", ".dll", ".dylib")) for name in names)
    after = {name: (ROOT / name).read_bytes() for name in before}
    assert after == before
    assert 'version = "0.37.8.dev5"' in before["pyproject.toml"].decode()


def test_probe_script_requires_every_functional_capability():
    assert len(functional_build.PROBES) == 6
    for name in functional_build.PROBES:
        assert f"has_live_video_trusted_vsi_{name}()" in functional_build.PROBE_SCRIPT


def test_functional_installed_qualification_removes_source_overrides():
    source = (ROOT / "scripts/qualify_trusted_vsi_functional.py").read_text()
    assert '"PYTHONPATH", "C2PA_LIBRARY_NAME"' in source
    assert 'C2PA_TRUSTED_VSI_FUNCTIONAL_REQUIRED="1"' in source
    assert 'C2PA_FUNCTIONAL_INSTALLED_ROOT=str(environment)' in source
    assert "timeout=480" in source
