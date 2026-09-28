"""Run functional tests against an installed qualification wheel, not src/."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv


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
               C2PA_FUNCTIONAL_EXPECTED_VERSION=args.version,
               C2PA_FUNCTIONAL_INSTALLED_ROOT=str(environment))
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "--ignore-installed",
                    str(args.wheel.resolve(strict=True))], cwd=environment, env=env, check=True)
    subprocess.run([str(python), "-m", "pytest", "-q",
                    str(root / "tests/test_trusted_vsi_api.py"), "-ra"],
                   cwd=environment, env=env, check=True, timeout=480)


if __name__ == "__main__":
    main()
