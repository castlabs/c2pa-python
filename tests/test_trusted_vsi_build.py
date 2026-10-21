"""Functional build identity is separate from immutable dev5 release inputs."""

import importlib.util
from pathlib import Path

import pytest
from packaging.utils import canonicalize_name, parse_sdist_filename
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "functional_build", ROOT / "scripts/build_trusted_vsi_functional.py")
functional_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(functional_build)


@pytest.mark.parametrize("version", [
    "0.37.13+signer.1.0.9", "0.37.14.dev0", "0.37.14.dev1", "0.38.0.dev1", "1.0.dev0+local",
])
def test_functional_source_or_future_development_version(version):
    assert functional_build.functional_version(version) == version


@pytest.mark.parametrize("version", [
    "0.37.8.dev5", "0.37.8.dev6", "0.37.8.dev5+functional", "0.37.7.dev1",
    "0.37.9", "0.38.0rc1", "invalid",
    # Historical functional qualification identities are older than the source.
    "0.37.9.dev0", "0.37.12.dev0", "0.37.13.dev0", "0.37.13.dev1",
    # Conformance-line prereleases merged into this line are older too.
    "0.37.12.dev4",
    "0.37.13.dev2", "0.37.13.dev3", "0.37.13",
    # The published 1.0.8 identity is historical; other final labels are not
    # this checkout's signer-aligned source identity.
    "0.37.13+signer.1.0.8", "0.37.13+signer.1.0.10",
    "0.37.13+signer.1.0.9.1", "0.37.14+signer.1.0.9",
])
def test_functional_build_rejects_release_or_dev5_identity(version):
    with pytest.raises(ValueError):
        functional_build.functional_version(version)


@pytest.mark.parametrize("selected_version", ["0.37.13+signer.1.0.9", "0.37.14.dev0"])
def test_staged_sdist_uses_new_version_without_touching_dev5_checkout(tmp_path, selected_version):
    import subprocess
    import sys
    import tarfile

    before = {name: (ROOT / name).read_bytes() for name in ("pyproject.toml", "src/c2pa/c2pa.py")}
    stage = tmp_path / "stage"
    stage.mkdir()
    functional_build.stage_source(stage, selected_version)
    assert f'version = "{selected_version}"' in (stage / "pyproject.toml").read_text()
    assert f"# Version: {selected_version}" in (stage / "src/c2pa/c2pa.py").read_text()
    assert not (stage / "src/c2pa/libs").exists()
    subprocess.run([sys.executable, "setup.py", "-q", "sdist", "--dist-dir", str(tmp_path / "dist")],
                   cwd=stage, check=True, capture_output=True)
    # setuptools < 69 names sdists "c2pa-python-<v>", newer "c2pa_python-<v>";
    # compare canonicalized name/version instead of one spelling.
    (sdist,) = (tmp_path / "dist").iterdir()
    name, version = parse_sdist_filename(sdist.name)
    assert canonicalize_name(name) == "c2pa-python"
    assert version == Version(selected_version)
    root = sdist.name[:-len(".tar.gz")]
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        info = archive.extractfile(f"{root}/PKG-INFO").read().decode()
    assert f"Version: {selected_version}" in info.splitlines()
    for member in ("scripts/build_trusted_vsi_functional.py",
                   "scripts/qualify_trusted_vsi_functional.py",
                   "docs/trusted-vsi-python-contract.md", "src/c2pa/c2pa.py"):
        assert f"{root}/{member}" in names
    assert not any(name.endswith((".so", ".dll", ".dylib")) for name in names)
    after = {name: (ROOT / name).read_bytes() for name in before}
    assert after == before
    # The checkout keeps its own source identity; staging never rewrites it.
    assert 'version = "0.37.13+signer.1.0.9"' in before["pyproject.toml"].decode()


def test_default_build_version_is_the_source_identity(monkeypatch):
    monkeypatch.delenv("FUNCTIONAL_BUILD_VERSION", raising=False)
    assert functional_build.source_version() == "0.37.13+signer.1.0.9"
    assert functional_build.functional_version(functional_build.source_version()) == "0.37.13+signer.1.0.9"


@pytest.mark.parametrize("version", ["0.37.13", "0.37.13+vendor.1"])
def test_final_source_without_signer_identity_is_not_qualified(tmp_path, version):
    (tmp_path / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    with pytest.raises(ValueError):
        functional_build.functional_version(version, tmp_path)


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
    for required in ('C2PA_REQUIRE_SIGN_LADDER="1"', 'C2PA_REQUIRE_FRAGMENTED_FILES="1"'):
        assert required in source
    for name in ("test_trusted_vsi_api.py", "test_fragmented_files.py",
                 "test_sign_ladder.py", "test_native_ownership.py",
                 "test_native_ownership_opaque.py"):
        assert f'"{name}"' in source


def test_ci_keeps_existing_trusted_author_and_label_gate():
    workflow = (ROOT / ".github/workflows/build.yml").read_text()
    gate = workflow.split("  trusted-vsi-paired:", 1)[1].split("  read-version:", 1)[0]
    assert "author_association == 'COLLABORATOR'" in gate
    assert "author_association == 'MEMBER'" in gate
    assert "contains(github.event.pull_request.labels.*.name, 'safe to test')" in gate
    assert "pull_request_target" not in workflow
    assert "      - labeled" in workflow
    assert "secrets: inherit" not in gate
