"""Run functional tests against an installed qualification wheel, not src/."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv


# test_trusted_vsi_api.py asserts the import resolves inside the venv, so the
# whole session is proven to exercise the installed wheel rather than src/.
INSTALLED_TESTS = (
    "test_trusted_vsi_api.py",
    "test_fragmented_files.py",
    "test_sign_ladder.py",
    "test_native_ownership.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    environment = args.venv.resolve()
    if environment.exists():
        parser.error("qualification venv must not already exist")
    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = dict(os.environ)
    for name in ("PYTHONPATH", "C2PA_LIBRARY_NAME", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        env.pop(name, None)
    env.update(C2PA_TRUSTED_VSI_ABI_REQUIRED="1",
               C2PA_TRUSTED_VSI_FUNCTIONAL_REQUIRED="1",
               C2PA_REQUIRE_SIGN_LADDER="1",
               C2PA_REQUIRE_FRAGMENTED_FILES="1",
               C2PA_FUNCTIONAL_EXPECTED_VERSION=args.version,
               C2PA_FUNCTIONAL_INSTALLED_ROOT=str(environment))
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--ignore-installed",
                    str(args.wheel.resolve(strict=True))], cwd=environment, env=env, check=True)
    subprocess.run([str(python), "-m", "pytest", "-q",
                    *(str(root / "tests" / name) for name in INSTALLED_TESTS), "-ra"],
                   cwd=environment, env=env, check=True, timeout=480)


if __name__ == "__main__":
    main()
