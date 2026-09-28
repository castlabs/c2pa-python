"""Build source-paired functional test artifacts, never release/publish dev5.

The development version is applied only in a temporary source staging tree.
The repository's version and immutable release inputs are left untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import sysconfig

import toml
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


def functional_version(value: str) -> str:
    version = Version(value)
    if (not version.is_devrelease or version <= Version("0.37.8.dev5")
            or version.release == (0, 37, 8)):
        raise ValueError("functional version must be a newer development series than 0.37.8")
    return str(version)


PROBES = (
    "split_init", "expert_sig_structure", "composed_emsg", "recovery",
    "signing_context_v1", "full_uint32_exhaustion",
)
PROBE_SCRIPT = "import c2pa\n" + "".join(
    f"assert c2pa.has_live_video_trusted_vsi_{name}(), {name!r}\n" for name in PROBES)
STAGED_DIRECTORIES = ("src", "scripts", "release", "docs", "tests")
STAGED_FILES = ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "LICENSE-MIT",
                "LICENSE-APACHE", "requirements.txt", "c2pa-native-version.txt")


def stage_source(stage: Path, version: str, root: Path = ROOT) -> None:
    """Copy the checkout into ``stage`` and apply ``version`` there only."""
    version = functional_version(version)
    for directory in STAGED_DIRECTORIES:
        if (root / directory).is_dir():
            shutil.copytree(root / directory, stage / directory, ignore=shutil.ignore_patterns(
                "__pycache__", "*.egg-info", "libs", "temp_data", "*.log"))
    for name in STAGED_FILES:
        shutil.copy2(root / name, stage / name)
    project = toml.load(stage / "pyproject.toml")
    source_version = project["project"]["version"]
    project["project"]["version"] = version
    (stage / "pyproject.toml").write_text(toml.dumps(project), encoding="utf-8")
    binding = stage / "src/c2pa/c2pa.py"
    text = binding.read_text(encoding="utf-8")
    marker = f"# Version: {source_version}"
    if marker not in text:
        raise ValueError("binding version header does not match pyproject.toml")
    binding.write_text(text.replace(marker, f"# Version: {version}", 1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--version", default=os.environ.get("FUNCTIONAL_BUILD_VERSION", "0.37.9.dev0"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    version = functional_version(args.version)
    library = args.library.resolve(strict=True)
    expected_name = {"linux": "libc2pa_c.so", "win32": "c2pa_c.dll", "darwin": "libc2pa_c.dylib"}[sys.platform]
    if library.name != expected_name:
        parser.error(f"expected the native library {expected_name}")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("output directory must be empty")

    # The actual paired library must qualify before any new artifact is built.
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), C2PA_LIBRARY_NAME=str(library))
    subprocess.run([sys.executable, "-c", PROBE_SCRIPT], env=env, cwd=ROOT, check=True)

    with tempfile.TemporaryDirectory(prefix="functional-build-", dir=output) as temporary:
        stage = Path(temporary)
        stage_source(stage, version)

        # Existing setup.py stages artifacts into the wheel and removes that
        # staging directory afterward. Do not touch the checkout's libs/ at all.
        platform_id = subprocess.check_output([
            sys.executable, "-c", "from c2pa.lib import get_platform_identifier; print(get_platform_identifier())",
        ], env=env, cwd=ROOT, text=True).strip()
        native_dir = stage / "artifacts" / platform_id
        native_dir.mkdir(parents=True)
        shutil.copy2(library, native_dir / library.name)
        build_env = dict(os.environ)
        build_env.pop("PYTHONPATH", None)
        subprocess.run([sys.executable, "setup.py", "sdist", "--dist-dir", str(output)],
                       cwd=stage, env=build_env, check=True)
        wheel_platform = sysconfig.get_platform().replace("-", "_").replace(".", "_")
        subprocess.run([sys.executable, "setup.py", "bdist_wheel", "--plat-name", wheel_platform,
                        "--dist-dir", str(output)],
                       cwd=stage, env=build_env, check=True)

    artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in output.iterdir() if p.is_file()}
    (output / "functional-build.json").write_text(json.dumps({
        "qualification_only": True,
        "python_version": version,
        "native_library": str(library),
        "native_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "artifacts": artifacts,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
