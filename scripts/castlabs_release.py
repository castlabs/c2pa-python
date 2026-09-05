#!/usr/bin/env python3

"""Hermetic release helpers for the Castlabs VSI prerelease."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "release" / "castlabs-vsi-inputs.lock.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_VERSION = "0.37.8.dev1"
RUST_COMMIT = "d511c7b96aba1f2be9f4eede4f76d70d2cd59bfa"
CARGO_LOCK_SHA256 = "c4554b8fd3a1d3a1dc00482546750a40b06d0e5a86c9e66f4830c63fbd0df70f"
RUST_TOOLCHAIN = "1.88.0"
MANYLINUX_IMAGE = "quay.io/pypa/manylinux_2_28_x86_64"
MANYLINUX_DIGEST = (
    "sha256:0d9c2a66a745961947a8cecbe217ca0a7ee7a5849ba2517f20f9581d18444977"
)
RELEASE_TAG = "castlabs-v0.37.8.dev1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_wheel_names() -> set[str]:
    lock = load_lock()
    validate_lock(lock)
    return {
        f"c2pa_python-{RELEASE_VERSION}-py3-none-" f"{target['wheelPlatformTag']}.whl"
        for target in lock["targets"].values()
    }


def expected_release_asset_names() -> set[str]:
    bundle_bases = {
        f"c2pa-python-{RELEASE_VERSION}-py3-none-wheels.tar.gz",
        f"c2pa-python-{RELEASE_VERSION}-native-linux-x86_64.tar.gz",
        f"c2pa-python-{RELEASE_VERSION}-native-windows-x86_64.tar.gz",
    }
    names = set(expected_wheel_names())
    for bundle in bundle_bases:
        names.update(
            {
                bundle,
                f"{bundle}.sha256",
                f"{bundle}.evidence.json",
                f"{bundle}.evidence.json.sha256",
            }
        )
    names.update(
        {
            "features-x86_64-unknown-linux-gnu.txt",
            "features-x86_64-pc-windows-msvc.txt",
        }
    )
    return names


def exact_files(
    directory: Path, expected: set[str], description: str
) -> dict[str, Path]:
    if not directory.is_dir() or directory.is_symlink():
        fail(f"{description} directory is missing or unsafe: {directory}")
    files: dict[str, Path] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.is_symlink():
            fail(f"{description} contains a non-regular file: {path}")
        files[path.name] = path
    actual = set(files)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        fail(
            f"{description} file set differs from policy; "
            f"missing={missing}, unexpected={unexpected}"
        )
    return files


def load_lock() -> dict[str, Any]:
    with LOCK_PATH.open("r", encoding="utf-8") as source:
        return json.load(source)


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def run_git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT
    ).strip()


def canonical_git_url(url: str) -> str:
    return url.removesuffix(".git").rstrip("/").lower()


def project_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        fail("project.version is missing from pyproject.toml")
    return match.group(1)


def cargo_selection(lock: dict[str, Any], target: str) -> list[str]:
    native = lock["nativeBuild"]
    return [
        "--locked",
        "--manifest-path",
        "c2pa_c_ffi/Cargo.toml",
        "--package",
        native["package"],
        "--target",
        target,
        "--no-default-features",
        "--features",
        ",".join(native["features"]),
    ]


def cargo_command(lock: dict[str, Any], target: str) -> list[str]:
    return [
        "cargo",
        f"+{lock['rustToolchain']['channel']}",
        "build",
        "--release",
        *cargo_selection(lock, target),
    ]


def cargo_tree_command(lock: dict[str, Any], target: str) -> list[str]:
    return [
        "cargo",
        f"+{lock['rustToolchain']['channel']}",
        "tree",
        *cargo_selection(lock, target),
        "--edges",
        "features",
        "--charset",
        "ascii",
        "--format",
        "{p}_features=[{f}]",
    ]


def validate_lock(lock: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "package",
        "pythonSource",
        "rustSource",
        "rustToolchain",
        "nativeBuild",
        "targets",
        "manylinux",
        "wheel",
    }
    if set(lock) != required or lock.get("schemaVersion") != 1:
        fail("release lock does not match schema version 1")
    if lock["package"] != {"name": "c2pa-python", "version": RELEASE_VERSION}:
        fail("release lock package identity is not 0.37.8.dev1")
    if lock["pythonSource"] != {
        "repository": "castlabs/c2pa-python",
        "url": "https://github.com/castlabs/c2pa-python.git",
        "releaseBranch": "feat/live-video-vsi",
        "releaseTag": "castlabs-v0.37.8.dev1",
    }:
        fail("unexpected c2pa-python release source policy")
    rust = lock["rustSource"]
    if rust != {
        "repository": "castlabs/c2pa-rs",
        "url": "https://github.com/castlabs/c2pa-rs.git",
        "commit": RUST_COMMIT,
        "version": "0.91.0-dev",
        "cargoLockSha256": CARGO_LOCK_SHA256,
    }:
        fail("unexpected c2pa-rs release source policy")
    if lock["rustToolchain"] != {
        "channel": RUST_TOOLCHAIN,
        "rustupVersion": "1.28.2",
        "installers": {
            "x86_64-unknown-linux-gnu": {
                "url": "https://static.rust-lang.org/rustup/archive/1.28.2/x86_64-unknown-linux-gnu/rustup-init",
                "sha256": "20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c",
            },
            "x86_64-pc-windows-msvc": {
                "url": "https://static.rust-lang.org/rustup/archive/1.28.2/x86_64-pc-windows-msvc/rustup-init.exe",
                "sha256": "88d8258dcf6ae4f7a80c7d1088e1f36fa7025a1cfd1343731b4ee6f385121fc0",
            },
        },
    }:
        fail("unexpected Rust toolchain policy")
    expected_features = [
        "rust_native_crypto",
        "http",
        "add_thumbnails",
        "file_io",
        "unstable_live_video",
    ]
    if lock["nativeBuild"] != {
        "package": "c2pa-c-ffi",
        "profile": "release",
        "noDefaultFeatures": True,
        "features": expected_features,
    }:
        fail("native build profile or features changed")
    if lock["targets"] != {
        "x86_64-unknown-linux-gnu": {
            "runner": "ubuntu-24.04",
            "library": "libc2pa_c.so",
            "wheelPlatformTag": "manylinux_2_28_x86_64",
        },
        "x86_64-pc-windows-msvc": {
            "runner": "windows-2022",
            "library": "c2pa_c.dll",
            "wheelPlatformTag": "win_amd64",
        },
    }:
        fail("release target policy changed")
    if lock["manylinux"] != {
        "image": MANYLINUX_IMAGE,
        "digest": MANYLINUX_DIGEST,
        "python": "/opt/python/cp310-cp310/bin/python",
    }:
        fail("manylinux build policy changed")
    if lock["wheel"] != {
        "pythonTag": "py3",
        "abiTag": "none",
        "testPythons": ["3.10", "3.11", "3.12", "3.13"],
    }:
        fail("wheel compatibility matrix changed")


def command_validate_lock(_: argparse.Namespace) -> None:
    validate_lock(load_lock())
    print(f"validated {LOCK_PATH.relative_to(ROOT)}")


def command_lock_value(args: argparse.Namespace) -> None:
    value: Any = load_lock()
    validate_lock(value)
    for component in args.path.split("."):
        value = value[component]
    if isinstance(value, (dict, list)):
        print(json.dumps(value, separators=(",", ":")))
    else:
        print(value)


def command_validate_sources(args: argparse.Namespace) -> None:
    lock = load_lock()
    validate_lock(lock)
    python_root = Path(args.python_root).resolve()
    rust_root = Path(args.rust_root).resolve()
    source_sha = args.source_sha.lower()
    if not SHA_RE.fullmatch(source_sha):
        fail("c2pa-python source SHA must be 40 lowercase hexadecimal digits")
    if args.repository != lock["pythonSource"]["repository"]:
        fail("workflow repository does not match the release lock")
    if canonical_git_url(run_git(python_root, "remote", "get-url", "origin")) != (
        canonical_git_url(lock["pythonSource"]["url"])
    ):
        fail("c2pa-python origin URL does not match the release lock")
    if run_git(python_root, "rev-parse", "HEAD") != source_sha:
        fail("c2pa-python checkout is not the requested full source SHA")
    if project_version(python_root) != lock["package"]["version"]:
        fail("pyproject.toml version does not match the release lock")
    expected_ref = (
        f"refs/tags/{lock['pythonSource']['releaseTag']}"
        if args.event == "tag"
        else f"refs/heads/{lock['pythonSource']['releaseBranch']}"
    )
    if args.ref != expected_ref:
        fail(f"release event ref must be {expected_ref}, not {args.ref}")
    if args.event == "manual":
        branch_tip = run_git(
            python_root,
            "rev-parse",
            f"refs/remotes/origin/{lock['pythonSource']['releaseBranch']}",
        )
        if branch_tip != source_sha:
            fail("manual release source must equal the locked release branch tip")
    rust = lock["rustSource"]
    if canonical_git_url(run_git(rust_root, "remote", "get-url", "origin")) != (
        canonical_git_url(rust["url"])
    ):
        fail("c2pa-rs origin URL does not match the release lock")
    if run_git(rust_root, "rev-parse", "HEAD") != rust["commit"]:
        fail("c2pa-rs checkout is not the locked full SHA")
    lock_digest = sha256_file(rust_root / "Cargo.lock")
    if lock_digest != rust["cargoLockSha256"]:
        fail("c2pa-rs Cargo.lock digest does not match the release lock")
    cargo_toml = (rust_root / "Cargo.toml").read_text(encoding="utf-8")
    version_match = re.search(
        r"\[workspace\.package\]\s+version\s*=\s*\"([^\"]+)\"",
        cargo_toml,
    )
    if not version_match or version_match.group(1) != rust["version"]:
        fail("c2pa-rs workspace version does not match the release lock")
    if run_git(python_root, "status", "--porcelain"):
        fail("c2pa-python release checkout is dirty")
    if run_git(rust_root, "status", "--porcelain"):
        fail("c2pa-rs release checkout is dirty")
    print(f"validated release sources {source_sha} and {rust['commit']}")


def command_cargo_build(args: argparse.Namespace) -> None:
    lock = load_lock()
    validate_lock(lock)
    if os.environ.get("CARGO_BUILD_JOBS") != "1":
        fail("CARGO_BUILD_JOBS must be 1 for release builds")
    target = args.target
    if target not in lock["targets"]:
        fail(f"unknown target: {target}")
    rust_root = Path(args.rust_root).resolve()
    report = Path(args.feature_report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    tree = subprocess.run(
        cargo_tree_command(lock, target),
        cwd=rust_root,
        check=True,
        stdout=subprocess.PIPE,
    )
    report.write_bytes(tree.stdout.replace(b"\r\n", b"\n"))
    command = cargo_command(lock, target)
    subprocess.run(command, cwd=rust_root, check=True)
    print(json.dumps(command, separators=(",", ":")))


def safe_archive_name(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if (
        not name
        or member.is_absolute()
        or ".." in member.parts
        or "\\" in name
        or member.as_posix() != name
    ):
        fail(f"unsafe archive member name: {name!r}")
    return member


def parse_mapping(value: str) -> tuple[str, Path]:
    key, separator, raw_path = value.partition("=")
    if not separator or not key or not raw_path:
        fail(f"expected NAME=PATH, got {value!r}")
    return key, Path(raw_path).resolve()


def deterministic_tar_gz(
    output: Path, members: list[tuple[Path, str]], epoch: int
) -> None:
    if not 315532800 <= epoch <= 0xFFFFFFFF:
        fail("SOURCE_DATE_EPOCH is outside the portable release range")
    normalized: list[tuple[Path, PurePosixPath]] = []
    names: set[str] = set()
    for source, name in members:
        archive_name = safe_archive_name(name)
        if not source.is_file() or source.is_symlink():
            fail(f"release member is not a regular file: {source}")
        if name in names:
            fail(f"duplicate release member: {name}")
        names.add(name)
        normalized.append((source, archive_name))
    if output.exists() or output.is_symlink():
        fail(f"refusing to replace release archive: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        fail(f"temporary release path already exists: {temporary}")
    try:
        with temporary.open("xb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=epoch) as gz:
                with tarfile.open(
                    fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT
                ) as archive:
                    for source, archive_name in sorted(
                        normalized, key=lambda item: item[1].as_posix()
                    ):
                        info = tarfile.TarInfo(archive_name.as_posix())
                        stat = source.stat()
                        info.size = stat.st_size
                        info.mtime = epoch
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mode = 0o644
                        with source.open("rb") as payload:
                            archive.addfile(info, payload)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def command_pack(args: argparse.Namespace) -> None:
    epoch = int(args.epoch)
    mappings = []
    for value in args.member:
        name, path = parse_mapping(value)
        mappings.append((path, name))
    deterministic_tar_gz(Path(args.output).resolve(), mappings, epoch)
    print(Path(args.output).resolve())


def command_extract(args: argparse.Namespace) -> None:
    archive_path = Path(args.archive).resolve()
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for info in archive.getmembers():
            name = safe_archive_name(info.name)
            if info.name in seen:
                fail(f"duplicate archive member: {info.name}")
            seen.add(info.name)
            if not info.isfile():
                fail(f"archive member is not a regular file: {info.name}")
            target = (destination / Path(*name.parts)).resolve()
            if not target.is_relative_to(destination):
                fail(f"archive member escapes destination: {info.name}")
            if target.exists() or target.is_symlink():
                fail(f"refusing to replace extracted file: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(info)
            if source is None:
                fail(f"could not read archive member: {info.name}")
            with target.open("wb") as output:
                output.write(source.read())
            target.chmod(info.mode & 0o777)
    print(destination)


def command_checksum(args: argparse.Namespace) -> None:
    artifact = Path(args.artifact).resolve()
    if not artifact.is_file() or artifact.is_symlink():
        fail(f"release artifact is not a regular file: {artifact}")
    output = (
        Path(args.output).resolve() if args.output else Path(str(artifact) + ".sha256")
    )
    if output.exists() or output.is_symlink():
        fail(f"refusing to replace checksum: {output}")
    output.write_text(f"{sha256_file(artifact)}  {artifact.name}\n", encoding="ascii")
    print(output)


def command_stage_native(args: argparse.Namespace) -> None:
    lock = load_lock()
    validate_lock(lock)
    target = args.target
    if target not in lock["targets"]:
        fail(f"unknown target: {target}")
    source = Path(args.source).resolve()
    expected_name = lock["targets"][target]["library"]
    if not source.is_file() or source.name != expected_name:
        fail(f"expected native library named {expected_name}: {source}")
    artifacts = ROOT / "artifacts" / target
    package_libs = ROOT / "src" / "c2pa" / "libs"
    for destination in (artifacts, package_libs):
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        shutil.copyfile(source, destination / expected_name)
    print(artifacts / expected_name)


def wheel_details_bytes(
    name: str, payload: bytes, target: str, interpreter: str
) -> dict[str, Any]:
    lock = load_lock()
    validate_lock(lock)
    if target not in lock["targets"]:
        fail(f"unknown wheel target: {target}")
    expected_name = (
        f"c2pa_python-{RELEASE_VERSION}-{lock['wheel']['pythonTag']}-"
        f"{lock['wheel']['abiTag']}-{lock['targets'][target]['wheelPlatformTag']}.whl"
    )
    if name != expected_name:
        fail(f"unexpected wheel filename for {target}: {name}")
    parts = name[:-4].rsplit("-", 3)
    if len(parts) != 4:
        fail(f"invalid wheel filename: {name}")
    _, python_tag, abi_tag, platform_tag = parts
    native_members: list[tuple[str, bytes]] = []
    metadata_members: list[bytes] = []
    wheel_members: list[bytes] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names: set[str] = set()
        for info in archive.infolist():
            member = safe_archive_name(info.filename.rstrip("/"))
            if info.filename in names:
                fail(f"duplicate wheel member: {info.filename}")
            names.add(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                fail(f"wheel contains a symlink: {info.filename}")
            if any(part.endswith(".libs") for part in member.parts):
                fail(f"wheel contains an unexpected auditwheel graft: {info.filename}")
            if info.is_dir():
                continue
            contents = archive.read(info)
            if member.parts[:2] == ("c2pa", "libs"):
                native_members.append((info.filename, contents))
            if info.filename.endswith(".dist-info/METADATA"):
                metadata_members.append(contents)
            if info.filename.endswith(".dist-info/WHEEL"):
                wheel_members.append(contents)
    if len(native_members) != 1:
        fail(f"wheel must contain exactly one native library: {name}")
    native_name, native_bytes = native_members[0]
    expected_native = f"c2pa/libs/{lock['targets'][target]['library']}"
    if native_name != expected_native:
        fail(f"unexpected native wheel member: {native_name}")
    if len(metadata_members) != 1 or len(wheel_members) != 1:
        fail(f"wheel must contain exactly one METADATA and WHEEL file: {name}")
    metadata = metadata_members[0].decode("utf-8")
    if "\nName: c2pa-python\n" not in f"\n{metadata}" or (
        f"\nVersion: {RELEASE_VERSION}\n" not in f"\n{metadata}"
    ):
        fail(f"wheel package metadata is incorrect: {name}")
    wheel_metadata = wheel_members[0].decode("utf-8")
    expected_tag = f"Tag: {python_tag}-{abi_tag}-{platform_tag}"
    wheel_tags = [
        line for line in wheel_metadata.splitlines() if line.startswith("Tag: ")
    ]
    if wheel_tags != [expected_tag]:
        fail(f"wheel metadata tags must be exactly [{expected_tag}]: {name}")
    return {
        "file": name,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "target": target,
        "nativeMember": native_name,
        "nativeSha256": hashlib.sha256(native_bytes).hexdigest(),
        "pythonTag": python_tag,
        "abiTag": abi_tag,
        "platformTag": platform_tag,
        "interpreter": interpreter,
    }


def wheel_details(path: Path, target: str, interpreter: str) -> dict[str, Any]:
    return wheel_details_bytes(path.name, path.read_bytes(), target, interpreter)


def command_verify_wheel_native(args: argparse.Namespace) -> None:
    lock = load_lock()
    validate_lock(lock)
    target = args.target
    if target not in lock["targets"]:
        fail(f"unknown wheel target: {target}")
    wheel = Path(args.wheel).resolve()
    qualified_native = Path(args.native).resolve()
    native_name = lock["targets"][target]["library"]
    if (
        not qualified_native.is_file()
        or qualified_native.is_symlink()
        or qualified_native.name != native_name
    ):
        fail(f"qualified native artifact is missing or misnamed: {qualified_native}")
    details = wheel_details(wheel, target, "wheel-native-verification")
    with zipfile.ZipFile(wheel) as archive:
        wheel_native = archive.read(details["nativeMember"])
    qualified_bytes = qualified_native.read_bytes()
    wheel_digest = hashlib.sha256(wheel_native).hexdigest()
    qualified_digest = hashlib.sha256(qualified_bytes).hexdigest()
    if wheel_digest != qualified_digest or wheel_native != qualified_bytes:
        fail(
            "final wheel native member differs from the qualified native artifact: "
            f"{wheel.name}"
        )
    output = Path(args.output).resolve()
    if output.name != native_name:
        fail(f"verified native output must be named {native_name}: {output}")
    if output.exists() or output.is_symlink():
        fail(f"refusing to replace verified wheel native output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(wheel_native)
    print(f"{wheel_digest}  {output}")


def archive_members(path: Path) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with tarfile.open(path, mode="r:gz") as archive:
        for info in archive.getmembers():
            safe_archive_name(info.name)
            if info.name in members:
                fail(f"duplicate archive member: {info.name}")
            if not info.isfile():
                fail(f"archive member is not a regular file: {info.name}")
            source = archive.extractfile(info)
            if source is None:
                fail(f"could not read archive member: {info.name}")
            members[info.name] = source.read()
    if not members:
        fail(f"release archive is empty: {path}")
    return members


def checked_reproducibility_environment() -> dict[str, str]:
    reproducibility_environment = {
        "CARGO_BUILD_JOBS": os.environ.get("CARGO_BUILD_JOBS"),
        "CARGO_INCREMENTAL": os.environ.get("CARGO_INCREMENTAL"),
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),
    }
    expected_environment = {
        "CARGO_BUILD_JOBS": "1",
        "CARGO_INCREMENTAL": "0",
        "PYTHONHASHSEED": "0",
    }
    if reproducibility_environment != expected_environment:
        fail(
            "release evidence environment differs from policy: "
            f"{reproducibility_environment}"
        )
    return {name: str(value) for name, value in reproducibility_environment.items()}


def command_build_facts(args: argparse.Namespace) -> None:
    lock = load_lock()
    validate_lock(lock)
    target = args.target
    if target not in lock["targets"]:
        fail(f"unknown target: {target}")
    reproducibility_environment = checked_reproducibility_environment()
    report = Path(args.feature_report).resolve()
    facts = {
        "target": target,
        "rustToolchain": lock["rustToolchain"]["channel"],
        "cargoCommand": cargo_command(lock, target),
        "cargoTreeCommand": cargo_tree_command(lock, target),
        "noDefaultFeatures": True,
        "features": lock["nativeBuild"]["features"],
        "resolvedFeatureReportSha256": sha256_file(report),
        "sourceDateEpoch": int(args.epoch),
        "cargoBuildJobs": reproducibility_environment["CARGO_BUILD_JOBS"],
        "cargoIncremental": reproducibility_environment["CARGO_INCREMENTAL"],
        "pythonHashSeed": reproducibility_environment["PYTHONHASHSEED"],
        "container": args.container,
        "interpreter": args.interpreter,
    }
    output = Path(args.output).resolve()
    if output.exists() or output.is_symlink():
        fail(f"refusing to replace build facts: {output}")
    output.write_text(
        json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_build_facts(paths: list[str]) -> dict[str, dict[str, Any]]:
    result = {}
    for raw_path in paths:
        path = Path(raw_path).resolve()
        facts = json.loads(path.read_text(encoding="utf-8"))
        target = facts.pop("target")
        if target in result:
            fail(f"duplicate build facts for {target}")
        result[target] = facts
    return result


def command_evidence(args: argparse.Namespace) -> None:
    lock = load_lock()
    validate_lock(lock)
    checked_reproducibility_environment()
    artifact = Path(args.artifact).resolve()
    source_sha = args.source_sha.lower()
    if not SHA_RE.fullmatch(source_sha):
        fail("source SHA must be a full lowercase commit SHA")
    build_facts = load_build_facts(args.build_facts)
    packed = archive_members(artifact)
    members = []
    mapped_targets: set[str] = set()
    expected_archive_names: set[str] = set()
    for mapping in args.member:
        target, path = parse_mapping(mapping)
        if target in mapped_targets:
            fail(f"duplicate evidence target: {target}")
        mapped_targets.add(target)
        if target not in build_facts:
            fail(f"missing build facts for {target}")
        if args.type == "wheel-bundle":
            archive_name = path.name
            expected_archive_names.add(archive_name)
            if archive_name not in packed or packed[archive_name] != path.read_bytes():
                fail(f"wheel bundle does not contain exact input wheel: {path}")
            member = wheel_details_bytes(
                archive_name,
                packed[archive_name],
                target,
                build_facts[target]["interpreter"],
            )
        else:
            library = lock["targets"][target]["library"]
            archive_name = f"{target}/{library}"
            expected_archive_names.add(archive_name)
            if archive_name not in packed or packed[archive_name] != path.read_bytes():
                fail(f"native bundle does not contain exact input library: {path}")
            payload = packed[archive_name]
            member = {
                "file": archive_name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "target": target,
                "nativeMember": library,
                "nativeSha256": hashlib.sha256(payload).hexdigest(),
                "interpreter": build_facts[target]["interpreter"],
            }
        members.append(member)
    if set(packed) != expected_archive_names:
        fail("release archive members do not exactly match evidence inputs")
    expected_targets = set(lock["targets"])
    if args.type == "wheel-bundle" and mapped_targets != expected_targets:
        fail("wheel bundle must contain exactly one wheel for every target")
    if args.type == "native-bundle" and len(mapped_targets) != 1:
        fail("native bundle must contain exactly one target")
    builds = []
    for target in sorted({member["target"] for member in members}):
        facts = dict(build_facts[target])
        facts.pop("interpreter")
        facts["target"] = target
        builds.append(facts)
    rust = lock["rustSource"]
    evidence = {
        "schemaVersion": 2,
        "artifact": {
            "type": args.type,
            "package": lock["package"]["name"],
            "version": lock["package"]["version"],
            "file": artifact.name,
            "size": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
            "members": sorted(members, key=lambda item: item["file"]),
        },
        "sources": {
            "c2paPython": {
                "repository": lock["pythonSource"]["repository"],
                "url": lock["pythonSource"]["url"],
                "commit": source_sha,
            },
            "c2paRs": {
                "repository": rust["repository"],
                "url": rust["url"],
                "commit": rust["commit"],
                "version": rust["version"],
                "cargoLockSha256": rust["cargoLockSha256"],
            },
        },
        "builds": builds,
        "runner": {
            "os": os.environ.get("RUNNER_OS", sys.platform),
            "arch": os.environ.get("RUNNER_ARCH", "unknown"),
            "name": os.environ.get("RUNNER_NAME", "local"),
            "image": os.environ.get("ImageOS", os.environ.get("Image", "local")),
        },
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY", "local"),
            "ref": os.environ.get("GITHUB_REF", "local"),
            "sha": os.environ.get("GITHUB_SHA", source_sha),
            "event": os.environ.get("GITHUB_EVENT_NAME", "local"),
            "runId": os.environ.get("GITHUB_RUN_ID", "local"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "runNumber": os.environ.get("GITHUB_RUN_NUMBER", "local"),
        },
    }
    output = Path(args.output).resolve()
    if output.exists() or output.is_symlink():
        fail(f"refusing to replace release evidence: {output}")
    validate_evidence(evidence, artifact.parent)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(output)


def validate_evidence(
    evidence: dict[str, Any], artifact_dir: Path, source_sha: str | None = None
) -> None:
    lock = load_lock()
    validate_lock(lock)
    if evidence.get("schemaVersion") != 2:
        fail("evidence schemaVersion must be 2")
    required = {"schemaVersion", "artifact", "sources", "builds", "runner", "workflow"}
    if set(evidence) != required:
        fail("evidence has missing or unknown top-level fields")
    artifact = evidence["artifact"]
    required_artifact = {
        "type",
        "package",
        "version",
        "file",
        "size",
        "sha256",
        "members",
    }
    if set(artifact) != required_artifact:
        fail("evidence artifact fields do not match schema 2")
    if artifact["type"] not in {"native-bundle", "wheel-bundle"}:
        fail("evidence artifact type is invalid")
    if artifact["package"] != "c2pa-python" or artifact["version"] != RELEASE_VERSION:
        fail("evidence package identity is incorrect")
    if not SHA256_RE.fullmatch(artifact["sha256"]):
        fail("evidence artifact SHA-256 is invalid")
    if safe_archive_name(artifact["file"]).parts != (artifact["file"],):
        fail("evidenced artifact filename must be a basename")
    artifact_path = artifact_dir / artifact["file"]
    if not artifact_path.is_file():
        fail(f"evidenced artifact is missing: {artifact_path}")
    if artifact_path.stat().st_size != artifact["size"]:
        fail("evidenced artifact size does not match")
    if sha256_file(artifact_path) != artifact["sha256"]:
        fail("evidenced artifact digest does not match")
    packed = archive_members(artifact_path)
    if not artifact["members"] or not evidence["builds"]:
        fail("evidence must contain members and builds")
    sources = evidence["sources"]
    if set(sources) != {"c2paPython", "c2paRs"}:
        fail("evidence source fields are incorrect")
    python_source = sources["c2paPython"]
    if set(python_source) != {"repository", "url", "commit"} or (
        python_source["repository"] != lock["pythonSource"]["repository"]
        or python_source["url"] != lock["pythonSource"]["url"]
        or not SHA_RE.fullmatch(python_source["commit"])
    ):
        fail("evidence has an unexpected Python source")
    if source_sha is not None and python_source["commit"] != source_sha:
        fail("evidence Python source does not match the expected release SHA")
    rust_source = sources["c2paRs"]
    if rust_source != {
        "repository": lock["rustSource"]["repository"],
        "url": lock["rustSource"]["url"],
        "commit": lock["rustSource"]["commit"],
        "version": lock["rustSource"]["version"],
        "cargoLockSha256": lock["rustSource"]["cargoLockSha256"],
    }:
        fail("evidence has an unexpected Rust source")
    targets = {member["target"] for member in artifact["members"]}
    if len(targets) != len(artifact["members"]):
        fail("evidence contains duplicate artifact targets")
    if artifact["type"] == "wheel-bundle" and targets != set(lock["targets"]):
        fail("wheel evidence must contain exactly one wheel for every target")
    if artifact["type"] == "native-bundle" and len(targets) != 1:
        fail("native evidence must contain exactly one target")
    build_targets = {build["target"] for build in evidence["builds"]}
    if len(build_targets) != len(evidence["builds"]) or build_targets != targets:
        fail("evidence build targets do not match artifact members")
    expected_build_fields = {
        "target",
        "rustToolchain",
        "cargoCommand",
        "cargoTreeCommand",
        "noDefaultFeatures",
        "features",
        "resolvedFeatureReportSha256",
        "sourceDateEpoch",
        "cargoBuildJobs",
        "cargoIncremental",
        "pythonHashSeed",
        "container",
    }
    for build in evidence["builds"]:
        if set(build) != expected_build_fields:
            fail("evidence build fields do not match schema 2")
        target = build["target"]
        if target not in lock["targets"]:
            fail(f"evidence has an unknown build target: {target}")
        if build["cargoCommand"] != cargo_command(lock, target):
            fail("evidence cargo command differs from the release lock")
        if build["cargoTreeCommand"] != cargo_tree_command(lock, target):
            fail("evidence cargo tree command differs from the release lock")
        if build["rustToolchain"] != lock["rustToolchain"]["channel"]:
            fail("evidence Rust toolchain differs from the release lock")
        if build["noDefaultFeatures"] is not True or (
            build["features"] != lock["nativeBuild"]["features"]
        ):
            fail("evidence native features differ from the release lock")
        if (
            build["cargoBuildJobs"] != "1"
            or build["cargoIncremental"] != "0"
            or (build["pythonHashSeed"] != "0")
        ):
            fail("evidence reproducibility environment is incorrect")
        if not isinstance(build["sourceDateEpoch"], int) or (
            build["sourceDateEpoch"] < 315532800
        ):
            fail("evidence SOURCE_DATE_EPOCH is invalid")
        expected_container = (
            f"{lock['manylinux']['image']}@{lock['manylinux']['digest']}"
            if target == "x86_64-unknown-linux-gnu"
            else None
        )
        if build["container"] != expected_container:
            fail("evidence build container differs from the release lock")
        if not SHA256_RE.fullmatch(build["resolvedFeatureReportSha256"]):
            fail("invalid feature report digest")
        feature_report = artifact_dir / f"features-{target}.txt"
        if not feature_report.is_file() or (
            sha256_file(feature_report) != build["resolvedFeatureReportSha256"]
        ):
            fail(f"feature report is missing or does not match for {target}")
    expected_archive_names: set[str] = set()
    for member in artifact["members"]:
        base_fields = {
            "file",
            "size",
            "sha256",
            "target",
            "nativeMember",
            "nativeSha256",
            "interpreter",
        }
        expected_fields = (
            base_fields | {"pythonTag", "abiTag", "platformTag"}
            if artifact["type"] == "wheel-bundle"
            else base_fields
        )
        if set(member) != expected_fields:
            fail("evidence artifact member fields do not match schema 2")
        target = member["target"]
        if not isinstance(member["interpreter"], str) or not member["interpreter"]:
            fail("evidence build interpreter is missing")
        if artifact["type"] == "wheel-bundle":
            expected = wheel_details_bytes(
                member["file"],
                packed.get(member["file"], b""),
                target,
                member["interpreter"],
            )
        else:
            library = lock["targets"][target]["library"]
            archive_name = f"{target}/{library}"
            payload = packed.get(archive_name, b"")
            expected = {
                "file": archive_name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "target": target,
                "nativeMember": library,
                "nativeSha256": hashlib.sha256(payload).hexdigest(),
                "interpreter": member["interpreter"],
            }
        if member != expected:
            fail(f"evidence member does not match final archive: {member['file']}")
        expected_archive_names.add(member["file"])
    if set(packed) != expected_archive_names:
        fail("final archive members do not exactly match evidence")
    expected_artifact_name = (
        f"c2pa-python-{RELEASE_VERSION}-py3-none-wheels.tar.gz"
        if artifact["type"] == "wheel-bundle"
        else {
            "x86_64-unknown-linux-gnu": (
                f"c2pa-python-{RELEASE_VERSION}-native-linux-x86_64.tar.gz"
            ),
            "x86_64-pc-windows-msvc": (
                f"c2pa-python-{RELEASE_VERSION}-native-windows-x86_64.tar.gz"
            ),
        }[next(iter(targets))]
    )
    if artifact["file"] != expected_artifact_name:
        fail("evidence artifact filename is incorrect")
    runner = evidence["runner"]
    if set(runner) != {"os", "arch", "name", "image"} or any(
        not isinstance(value, str) or not value for value in runner.values()
    ):
        fail("evidence runner fields do not match schema 2")
    if set(evidence["workflow"]) != {
        "repository",
        "ref",
        "sha",
        "event",
        "runId",
        "runAttempt",
        "runNumber",
    }:
        fail("evidence workflow fields do not match schema 2")
    workflow = evidence["workflow"]
    if any(not isinstance(value, str) or not value for value in workflow.values()) or (
        not SHA_RE.fullmatch(workflow["sha"])
    ):
        fail("evidence workflow values do not match schema 2")
    if workflow["repository"] != "local":
        if workflow["repository"] != lock["pythonSource"]["repository"] or (
            workflow["sha"] != python_source["commit"]
        ):
            fail("evidence workflow source is incorrect")
        allowed_events = {
            f"refs/heads/{lock['pythonSource']['releaseBranch']}": "workflow_dispatch",
            f"refs/tags/{lock['pythonSource']['releaseTag']}": "push",
        }
        if allowed_events.get(workflow["ref"]) != workflow["event"]:
            fail("evidence workflow ref is not a release ref")


def command_validate_evidence(args: argparse.Namespace) -> None:
    path = Path(args.evidence).resolve()
    evidence = json.loads(path.read_text(encoding="utf-8"))
    expected_source = args.source_sha.lower() if args.source_sha else None
    if expected_source is not None and not SHA_RE.fullmatch(expected_source):
        fail("expected source SHA must be 40 lowercase hexadecimal digits")
    validate_evidence(
        evidence, Path(args.artifact_dir).resolve(), source_sha=expected_source
    )
    print(f"validated {path}")


def command_validate_release_assets(args: argparse.Namespace) -> None:
    directory = Path(args.assets_dir).resolve()
    files = exact_files(directory, expected_release_asset_names(), "release assets")
    evidence_names = [
        f"c2pa-python-{RELEASE_VERSION}-py3-none-wheels.tar.gz.evidence.json",
        f"c2pa-python-{RELEASE_VERSION}-native-linux-x86_64.tar.gz.evidence.json",
        f"c2pa-python-{RELEASE_VERSION}-native-windows-x86_64.tar.gz.evidence.json",
    ]
    evidences = []
    for name in evidence_names:
        evidence = json.loads(files[name].read_text(encoding="utf-8"))
        validate_evidence(evidence, directory)
        evidences.append(evidence)
    validate_release_evidence_consistency(evidences)
    print(f"validated {directory}")


def validate_release_evidence_consistency(evidences: list[dict[str, Any]]) -> None:
    wheel_evidence = [
        evidence
        for evidence in evidences
        if evidence.get("artifact", {}).get("type") == "wheel-bundle"
    ]
    native_evidence = [
        evidence
        for evidence in evidences
        if evidence.get("artifact", {}).get("type") == "native-bundle"
    ]
    if len(wheel_evidence) != 1 or len(native_evidence) != 2:
        fail("release evidence set must contain one wheel and two native bundles")
    wheel_digests = {
        member["target"]: member["nativeSha256"]
        for member in wheel_evidence[0]["artifact"]["members"]
    }
    native_digests: dict[str, str] = {}
    for evidence in native_evidence:
        members = evidence["artifact"]["members"]
        if len(members) != 1 or members[0]["target"] in native_digests:
            fail("release native evidence has duplicate or invalid targets")
        native_digests[members[0]["target"]] = members[0]["nativeSha256"]
    if wheel_digests != native_digests:
        fail("wheel and native bundle evidence contain different native digests")


def load_optional_json(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    values = []
    offset = 0
    try:
        while offset < len(text):
            value, offset = decoder.raw_decode(text, offset)
            values.append(value)
            while offset < len(text) and text[offset].isspace():
                offset += 1
    except json.JSONDecodeError as error:
        fail(f"invalid JSON in {path}: {error}")
    if len(values) > 1:
        fail(f"multiple GitHub releases or drafts found for tag {RELEASE_TAG}")
    if len(values) != 1 or not isinstance(values[0], dict):
        fail(f"expected one GitHub release JSON object in {path}")
    return values[0]


def inspect_draft_release(
    assets_dir: Path, release_data: dict[str, Any] | None
) -> dict[str, Any]:
    local = exact_files(
        assets_dir, expected_release_asset_names(), "local release assets"
    )
    if release_data is None:
        return {
            "schemaVersion": 1,
            "tag": RELEASE_TAG,
            "releaseExists": False,
            "releaseId": None,
            "existing": [],
            "missing": sorted(local),
        }
    if release_data.get("tag_name") != RELEASE_TAG:
        fail("existing GitHub release has the wrong tag")
    if release_data.get("draft") is not True:
        fail("existing GitHub release is published; refusing to modify it")
    if release_data.get("prerelease") is not True:
        fail("existing GitHub draft is not marked as a prerelease")
    release_id = release_data.get("id")
    if not isinstance(release_id, int) or release_id <= 0:
        fail("existing GitHub draft has an invalid release ID")
    remote_assets = release_data.get("assets")
    if not isinstance(remote_assets, list):
        fail("existing GitHub draft has an invalid asset list")
    existing = []
    names: set[str] = set()
    for remote in remote_assets:
        if not isinstance(remote, dict):
            fail("existing GitHub draft has an invalid asset")
        name = remote.get("name")
        if name not in local:
            fail(f"existing GitHub draft has an unexpected asset: {name!r}")
        if name in names:
            fail(f"existing GitHub draft has duplicate asset name: {name}")
        names.add(name)
        asset_id = remote.get("id")
        if not isinstance(asset_id, int) or asset_id <= 0:
            fail(f"existing GitHub asset has an invalid ID: {name}")
        if remote.get("state") not in (None, "uploaded"):
            fail(f"existing GitHub asset is not fully uploaded: {name}")
        size = remote.get("size")
        if size != local[name].stat().st_size:
            fail(f"existing GitHub asset size differs from local output: {name}")
        local_digest = sha256_file(local[name])
        api_digest = remote.get("digest")
        if api_digest not in (None, "", f"sha256:{local_digest}"):
            fail(f"existing GitHub asset digest differs from local output: {name}")
        existing.append(
            {
                "id": asset_id,
                "name": name,
                "size": size,
                "sha256": local_digest,
            }
        )
    return {
        "schemaVersion": 1,
        "tag": RELEASE_TAG,
        "releaseExists": True,
        "releaseId": release_id,
        "existing": sorted(existing, key=lambda item: item["name"]),
        "missing": sorted(set(local) - names),
    }


def write_json_new(path: Path, value: Any, description: str) -> None:
    if path.exists() or path.is_symlink():
        fail(f"refusing to replace {description}: {path}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def command_inspect_draft_release(args: argparse.Namespace) -> None:
    assets_dir = Path(args.assets_dir).resolve()
    release_data = load_optional_json(Path(args.release_json).resolve())
    plan = inspect_draft_release(assets_dir, release_data)
    plan_path = Path(args.plan).resolve()
    download_list = Path(args.download_list).resolve()
    write_json_new(plan_path, plan, "draft release plan")
    if download_list.exists() or download_list.is_symlink():
        fail(f"refusing to replace draft download list: {download_list}")
    download_list.write_text(
        "".join(f"{item['id']}\t{item['name']}\n" for item in plan["existing"]),
        encoding="utf-8",
    )
    print(plan_path)


def verify_draft_release(
    assets_dir: Path,
    existing_dir: Path,
    plan: dict[str, Any],
    require_complete: bool = False,
) -> list[str]:
    local = exact_files(
        assets_dir, expected_release_asset_names(), "local release assets"
    )
    expected_plan_fields = {
        "schemaVersion",
        "tag",
        "releaseExists",
        "releaseId",
        "existing",
        "missing",
    }
    if set(plan) != expected_plan_fields or plan.get("schemaVersion") != 1:
        fail("draft release plan has invalid fields")
    if plan.get("tag") != RELEASE_TAG or not isinstance(plan.get("existing"), list):
        fail("draft release plan has invalid release identity")
    existing_items = plan["existing"]
    existing_names = {item.get("name") for item in existing_items}
    if len(existing_names) != len(existing_items) or not existing_names <= set(local):
        fail("draft release plan has invalid existing assets")
    downloaded = exact_files(existing_dir, existing_names, "downloaded draft assets")
    for item in existing_items:
        if set(item) != {"id", "name", "size", "sha256"}:
            fail("draft release plan has invalid asset fields")
        path = downloaded[item["name"]]
        if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
            fail(f"downloaded draft asset differs from local output: {item['name']}")
        if path.read_bytes() != local[item["name"]].read_bytes():
            fail(
                f"downloaded draft asset bytes differ from local output: {item['name']}"
            )
    missing = sorted(set(local) - existing_names)
    if plan.get("missing") != missing:
        fail("draft release plan missing-asset set is inconsistent")
    if require_complete and missing:
        fail(f"GitHub draft release is incomplete: {missing}")
    return missing


def command_verify_draft_release(args: argparse.Namespace) -> None:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    missing = verify_draft_release(
        Path(args.assets_dir).resolve(),
        Path(args.existing_dir).resolve(),
        plan,
        require_complete=args.require_complete,
    )
    output = Path(args.missing_list).resolve()
    if output.exists() or output.is_symlink():
        fail(f"refusing to replace missing-asset list: {output}")
    output.write_text("".join(f"{name}\n" for name in missing), encoding="utf-8")
    print(output)


def pypi_missing_wheels(
    wheels_dir: Path, http_status: int, response: dict[str, Any] | None
) -> tuple[dict[str, Path], list[str]]:
    wheels = exact_files(wheels_dir, expected_wheel_names(), "PyPI wheel inputs")
    if http_status == 404:
        return wheels, sorted(wheels)
    if http_status != 200 or not isinstance(response, dict):
        fail(f"unexpected PyPI JSON API status: {http_status}")
    info = response.get("info")
    if (
        not isinstance(info, dict)
        or info.get("version") != RELEASE_VERSION
        or (str(info.get("name", "")).lower().replace("_", "-") != "c2pa-python")
    ):
        fail("PyPI JSON response has the wrong package or release version")
    urls = response.get("urls")
    if not isinstance(urls, list):
        fail("PyPI JSON response has no release file list")
    existing: set[str] = set()
    for item in urls:
        if not isinstance(item, dict):
            fail("PyPI JSON response contains an invalid release file")
        name = item.get("filename")
        if name not in wheels:
            fail(f"PyPI release contains an unexpected file: {name!r}")
        if name in existing:
            fail(f"PyPI release contains a duplicate filename: {name}")
        existing.add(name)
        if item.get("packagetype") != "bdist_wheel":
            fail(f"PyPI release file is not a wheel: {name}")
        digests = item.get("digests")
        if not isinstance(digests, dict) or digests.get("sha256") != sha256_file(
            wheels[name]
        ):
            fail(f"PyPI release digest differs from local wheel: {name}")
    return wheels, sorted(set(wheels) - existing)


def command_pypi_plan(args: argparse.Namespace) -> None:
    status = int(args.http_status)
    response = (
        json.loads(Path(args.response).read_text(encoding="utf-8"))
        if status == 200
        else None
    )
    wheels, missing = pypi_missing_wheels(
        Path(args.wheels_dir).resolve(), status, response
    )
    destination = Path(args.destination).resolve()
    if destination.exists() or destination.is_symlink():
        fail(f"refusing to replace PyPI upload directory: {destination}")
    destination.mkdir(parents=True)
    for name in missing:
        shutil.copyfile(wheels[name], destination / name)
    plan = {
        "schemaVersion": 1,
        "version": RELEASE_VERSION,
        "existing": sorted(set(wheels) - set(missing)),
        "missing": missing,
    }
    write_json_new(Path(args.output).resolve(), plan, "PyPI upload plan")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as output:
            output.write(f"upload={'true' if missing else 'false'}\n")
    print(json.dumps(plan, separators=(",", ":")))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    validate_lock_parser = commands.add_parser("validate-lock")
    validate_lock_parser.set_defaults(func=command_validate_lock)

    value_parser = commands.add_parser("lock-value")
    value_parser.add_argument("path")
    value_parser.set_defaults(func=command_lock_value)

    sources = commands.add_parser("validate-sources")
    sources.add_argument("--python-root", required=True)
    sources.add_argument("--rust-root", required=True)
    sources.add_argument("--source-sha", required=True)
    sources.add_argument("--repository", required=True)
    sources.add_argument("--event", choices=("manual", "tag"), required=True)
    sources.add_argument("--ref", required=True)
    sources.set_defaults(func=command_validate_sources)

    cargo = commands.add_parser("cargo-build")
    cargo.add_argument("--rust-root", required=True)
    cargo.add_argument("--target", required=True)
    cargo.add_argument("--feature-report", required=True)
    cargo.set_defaults(func=command_cargo_build)

    pack = commands.add_parser("pack")
    pack.add_argument("--output", required=True)
    pack.add_argument("--epoch", required=True)
    pack.add_argument("--member", action="append", required=True)
    pack.set_defaults(func=command_pack)

    extract = commands.add_parser("extract")
    extract.add_argument("--archive", required=True)
    extract.add_argument("--destination", required=True)
    extract.set_defaults(func=command_extract)

    checksum = commands.add_parser("checksum")
    checksum.add_argument("--artifact", required=True)
    checksum.add_argument("--output")
    checksum.set_defaults(func=command_checksum)

    stage = commands.add_parser("stage-native")
    stage.add_argument("--target", required=True)
    stage.add_argument("--source", required=True)
    stage.set_defaults(func=command_stage_native)

    verify_wheel = commands.add_parser("verify-wheel-native")
    verify_wheel.add_argument("--wheel", required=True)
    verify_wheel.add_argument("--target", required=True)
    verify_wheel.add_argument("--native", required=True)
    verify_wheel.add_argument("--output", required=True)
    verify_wheel.set_defaults(func=command_verify_wheel_native)

    facts = commands.add_parser("build-facts")
    facts.add_argument("--target", required=True)
    facts.add_argument("--feature-report", required=True)
    facts.add_argument("--epoch", required=True)
    facts.add_argument("--interpreter", required=True)
    facts.add_argument("--container")
    facts.add_argument("--output", required=True)
    facts.set_defaults(func=command_build_facts)

    evidence = commands.add_parser("evidence")
    evidence.add_argument("--artifact", required=True)
    evidence.add_argument(
        "--type", choices=("native-bundle", "wheel-bundle"), required=True
    )
    evidence.add_argument("--source-sha", required=True)
    evidence.add_argument("--member", action="append", required=True)
    evidence.add_argument("--build-facts", action="append", required=True)
    evidence.add_argument("--output", required=True)
    evidence.set_defaults(func=command_evidence)

    validate = commands.add_parser("validate-evidence")
    validate.add_argument("--evidence", required=True)
    validate.add_argument("--artifact-dir", required=True)
    validate.add_argument("--source-sha")
    validate.set_defaults(func=command_validate_evidence)

    release_assets = commands.add_parser("validate-release-assets")
    release_assets.add_argument("--assets-dir", required=True)
    release_assets.set_defaults(func=command_validate_release_assets)

    inspect_draft = commands.add_parser("inspect-draft-release")
    inspect_draft.add_argument("--assets-dir", required=True)
    inspect_draft.add_argument("--release-json", required=True)
    inspect_draft.add_argument("--plan", required=True)
    inspect_draft.add_argument("--download-list", required=True)
    inspect_draft.set_defaults(func=command_inspect_draft_release)

    verify_draft = commands.add_parser("verify-draft-release")
    verify_draft.add_argument("--assets-dir", required=True)
    verify_draft.add_argument("--existing-dir", required=True)
    verify_draft.add_argument("--plan", required=True)
    verify_draft.add_argument("--missing-list", required=True)
    verify_draft.add_argument("--require-complete", action="store_true")
    verify_draft.set_defaults(func=command_verify_draft_release)

    pypi = commands.add_parser("pypi-plan")
    pypi.add_argument("--wheels-dir", required=True)
    pypi.add_argument("--response", required=True)
    pypi.add_argument("--http-status", required=True)
    pypi.add_argument("--destination", required=True)
    pypi.add_argument("--output", required=True)
    pypi.add_argument("--github-output")
    pypi.set_defaults(func=command_pypi_plan)
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
