from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tarfile
import tempfile
import textwrap
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCE_SHA = "a" * 40
SCRIPT_PATH = ROOT / "scripts" / "castlabs_release.py"
SPEC = importlib.util.spec_from_file_location("castlabs_release", SCRIPT_PATH)
release = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(release)


def test_prerelease_version_is_consistent():
    assert release.project_version(ROOT) == "0.37.8.dev5"
    first_line = (
        (ROOT / "src" / "c2pa" / "c2pa.py").read_text(encoding="utf-8").splitlines()[13]
    )
    assert first_line == "# Version: 0.37.8.dev5"


def test_release_lock_and_schemas_are_valid_json():
    lock = release.load_lock()
    release.validate_lock(lock)
    assert lock["rustSource"]["commit"] == release.RUST_COMMIT
    assert lock["rustSource"]["cargoLockSha256"] == release.CARGO_LOCK_SHA256
    assert lock["rustToolchain"]["channel"] == "1.88.0"
    for name in (
        "castlabs-vsi-inputs.schema.json",
        "castlabs-release-evidence.schema.json",
    ):
        schema = json.loads((ROOT / "release" / name).read_text(encoding="utf-8"))
        assert schema["$schema"].endswith("2020-12/schema")
    if importlib.util.find_spec("jsonschema") is not None:
        import jsonschema

        schema = json.loads(
            (ROOT / "release" / "castlabs-vsi-inputs.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(lock, schema)


def test_trusted_vsi_workflows_isolate_paired_abi_from_dev5():
    workflow_dir = ROOT / ".github" / "workflows"
    paired = (workflow_dir / "trusted-vsi-paired.yml").read_text(encoding="utf-8")
    legacy = (workflow_dir / "build.yml").read_text(encoding="utf-8")
    dedicated = (workflow_dir / "castlabs-vsi-release.yml").read_text(encoding="utf-8")
    for caller in (legacy, dedicated):
        assert "uses: ./.github/workflows/trusted-vsi-paired.yml" in caller
    assert legacy.count('tests/test_trusted_vsi_api.py -k "not paired"') == 2
    assert "if: github.event_name == 'workflow_dispatch' && inputs.trusted_vsi_only" in dedicated
    assert "  prepare:\n    if: ${{ !inputs.trusted_vsi_only }}" in dedicated
    assert dedicated.count(f"ref: {release.RUST_COMMIT}") == 3
    assert 'C2PA_TRUSTED_VSI_ABI_REQUIRED: "1"' in paired
    assert "python -m pytest -q tests/test_trusted_vsi_api.py -ra" in paired
    assert "-k " not in paired
    assert "ubuntu-24.04" in paired and "windows-2022" in paired
    assert "C2PA_LIBRARY_NAME: ${{ github.workspace }}/paired-rust/target/debug/" in paired
    assert "PYTHONPATH: ${{ github.workspace }}/python-source/src" in paired
    assert "python setup.py egg_info" in paired
    assert "cargo +1.88.0 build --locked" in paired
    assert re.search(r"^\s+ref: [0-9a-f]{40}$", paired, re.MULTILINE)
    assert "ref: feat/" not in paired
    for forbidden in ("download_artifacts.py", "castlabs_release.py",
                      "upload-artifact@", "bdist_wheel", "contents: write",
                      "id-token: write", "continue-on-error", "gh release"):
        assert forbidden not in paired


def test_release_workflows_are_pinned_bounded_and_do_not_drift_from_helper(
    tmp_path,
):
    release_workflow = (
        ROOT / ".github" / "workflows" / "castlabs-vsi-release.yml"
    ).read_text(encoding="utf-8")
    pypi_workflow = (
        ROOT / ".github" / "workflows" / "castlabs-vsi-pypi.yml"
    ).read_text(encoding="utf-8")
    legacy_workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8"
    )
    paired_workflow = (
        ROOT / ".github" / "workflows" / "trusted-vsi-paired.yml"
    ).read_text(encoding="utf-8")
    for workflow in (release_workflow, pypi_workflow, paired_workflow):
        action_shas = re.findall(
            r"^\s*(?:-\s+)?uses:\s+[^@\s]+@([0-9a-f]{40})(?:\s+#.*)?$",
            workflow,
            re.MULTILINE,
        )
        local_calls = workflow.count(
            "uses: ./.github/workflows/trusted-vsi-paired.yml"
        )
        assert local_calls == (1 if workflow == release_workflow else 0)
        assert len(action_shas) + local_calls == workflow.count("uses:")
        assert "mstattma/" not in workflow
    assert release_workflow.count("timeout-minutes:") == 6
    assert pypi_workflow.count("timeout-minutes:") == 1
    assert "permissions:\n  contents: read" in release_workflow
    assert "attestations: write" in release_workflow
    assert "id-token: write" in release_workflow
    assert "attestations: read" in pypi_workflow
    assert 'CARGO_BUILD_JOBS: "1"' in release_workflow
    assert 'CARGO_INCREMENTAL: "0"' in release_workflow
    assert 'PYTHONHASHSEED: "0"' in release_workflow
    assert "-e CARGO_INCREMENTAL=0 -e PYTHONHASHSEED=0" in release_workflow
    assert release_workflow.count("castlabs_release.py cargo-build") == 2
    assert "cargo build " not in release_workflow
    assert "cargo tree " not in release_workflow
    assert 'python: ["3.10", "3.11", "3.12", "3.13"]' in release_workflow
    assert "continue-on-error" not in release_workflow
    assert '"${IMAGE}@${DIGEST}"' in release_workflow
    rust_inputs = {
        "RUSTUP_URL": "rustToolchain.installers.x86_64-unknown-linux-gnu.url",
        "RUSTUP_SHA": "rustToolchain.installers.x86_64-unknown-linux-gnu.sha256",
        "RUST_TOOLCHAIN": "rustToolchain.channel",
    }
    for variable, lock_path in rust_inputs.items():
        assert (
            f"{variable}=$(python3 c2pa-python/scripts/castlabs_release.py lock-value {lock_path})"
            in release_workflow
        )
        assert f'-e "{variable}=${{{variable}}}"' in release_workflow
    assert "command -v patchelf" in release_workflow
    assert (
        "-m auditwheel repair \\\n                --only-plat --plat manylinux_2_28_x86_64"
        in release_workflow
    )
    assert (
        "c2pa_python-0.37.8.dev5-py3-none-manylinux_2_28_x86_64.whl" in release_workflow
    )
    assert release_workflow.count("verify-wheel-native") == 2
    assert release_workflow.index("--only-plat --plat manylinux_2_28_x86_64") < (
        release_workflow.index("verify-wheel-native")
    )
    assert "cp artifacts/x86_64-unknown-linux-gnu/libc2pa_c.so" not in (
        release_workflow
    )
    assert "Copy-Item artifacts/x86_64-pc-windows-msvc/c2pa_c.dll" not in (
        release_workflow
    )
    assert 'test "$CARGO_INCREMENTAL" = 0' in release_workflow
    assert 'test "$PYTHONHASHSEED" = 0' in release_workflow
    linux_container = release_workflow.index("docker run --rm")
    linux_cargo = release_workflow.index(
        "scripts/castlabs_release.py cargo-build", linux_container
    )
    assert (
        release_workflow.index('test "$CARGO_INCREMENTAL" = 0', linux_container)
        < linux_cargo
    )
    assert (
        release_workflow.index('test "$PYTHONHASHSEED" = 0', linux_container)
        < linux_cargo
    )
    assert "Install pinned wheel-build Python" in release_workflow
    windows_job = release_workflow.index("  windows:\n")
    windows_checkout = release_workflow.index(
        "Checkout Castlabs Python source at full SHA", windows_job
    )
    windows_git_policy = release_workflow.index(
        "Validate byte-preserving Git checkout policy", windows_job
    )
    assert windows_git_policy < windows_checkout
    for setting in (
        'GIT_CONFIG_COUNT: "2"',
        "GIT_CONFIG_KEY_0: core.autocrlf",
        'GIT_CONFIG_VALUE_0: "false"',
        "GIT_CONFIG_KEY_1: core.eol",
        "GIT_CONFIG_VALUE_1: lf",
        'git config --get core.autocrlf) -ne "false"',
        'git config --get core.eol) -ne "lf"',
        "Get-FileHash c2pa-rs/Cargo.lock -Algorithm SHA256",
        "lock-value rustSource.cargoLockSha256",
    ):
        assert setting in release_workflow
    assert (
        "python3 -m pytest -q c2pa-python/tests/test_castlabs_release_tooling.py"
        in (release_workflow)
    )
    assert "if: github.ref == 'refs/tags/castlabs-v0.37.8.dev5'" in release_workflow
    assert "-F draft=true -F prerelease=true" in release_workflow
    assert "--clobber" not in release_workflow
    assert "repos/castlabs/c2pa-python/releases" in release_workflow
    assert "inspect-draft-release" in release_workflow
    assert release_workflow.count("inspect-draft-release") == 3
    assert release_workflow.count("verify-draft-release") == 2
    assert "gh release upload" not in release_workflow
    assert release_workflow.count("--paginate") == 1
    assert "query_release_id" in release_workflow
    assert "release-created-response.json" in release_workflow
    assert "extract-release-id" in release_workflow
    assert "validate-owned-empty-draft" in release_workflow
    assert "validate-created-release" in release_workflow
    assert "--jq .id" not in release_workflow
    assert "target_commitish=$SOURCE_SHA" in release_workflow
    assert (
        "https://uploads.github.com/repos/castlabs/c2pa-python/releases/"
        "${RELEASE_ID}/assets?name=${asset_name}" in release_workflow
    )
    assert "validate-upload-response" in release_workflow
    assert release_workflow.count("return 0") >= 5
    assert "CREATED_DRAFT_ID" in release_workflow
    assert "CLEANUP_ARMED=1" in release_workflow
    create_response = release_workflow.index("> release-created-response.json")
    extract_id = release_workflow.index("extract-release-id", create_response)
    exact_query = release_workflow.index("query_release_id", extract_id)
    owned_empty = release_workflow.index("validate-owned-empty-draft", exact_query)
    cleanup_armed = release_workflow.index("CLEANUP_ARMED=1", owned_empty)
    strict_create = release_workflow.index("validate-created-release", cleanup_armed)
    assert create_response < extract_id < exact_query < owned_empty < cleanup_armed
    assert cleanup_armed < strict_create
    creation_branch = release_workflow.index('if [[ "$RELEASE_EXISTS" == true ]]')
    pre_create_tag_check = release_workflow.index("verify_tag_source", creation_branch)
    create_post = release_workflow.index(
        "repos/castlabs/c2pa-python/releases \\", pre_create_tag_check
    )
    assert pre_create_tag_check < create_post
    assert release_workflow.index(
        "CLEANUP_ARMED=0", release_workflow.index("upload_missing()")
    ) < release_workflow.index(
        "https://uploads.github.com", release_workflow.index("upload_missing()")
    )
    assert "releases/${CREATED_DRAFT_ID}" in release_workflow
    assert "gh api --method DELETE" in release_workflow
    assert "gh release delete" not in release_workflow
    cleanup_block = release_workflow[
        release_workflow.index("cleanup_current_draft() {") : release_workflow.index(
            "discover_release() {"
        )
    ]
    assert "validate-owned-empty-draft" in cleanup_block
    assert "validate-created-release" not in cleanup_block
    assert release_workflow.count("verify_tag_source") == 3
    final_tag_check = release_workflow.rindex("verify_tag_source")
    final_query = release_workflow.index(
        'query_release_id "$RELEASE_ID" release-final.json'
    )
    assert final_tag_check < final_query
    assert release_workflow.index("attest-build-provenance@") < (
        release_workflow.index("inspect-draft-release")
    )
    assert "environment: pypipublish" in pypi_workflow
    assert ".draft == false and .prerelease == true" in pypi_workflow
    assert (
        "python3 -m pytest -q c2pa-python/tests/test_castlabs_release_tooling.py"
        in (pypi_workflow)
    )
    assert "for ARTIFACT in download/*" in pypi_workflow
    assert (
        "--signer-workflow castlabs/c2pa-python/.github/workflows/castlabs-vsi-release.yml"
        in pypi_workflow
    )
    assert '--signer-digest "$SOURCE_SHA"' in pypi_workflow
    assert "--source-ref refs/tags/castlabs-v0.37.8.dev5" in pypi_workflow
    assert '--source-digest "$SOURCE_SHA"' in pypi_workflow
    assert "pypi.org/pypi/c2pa-python/0.37.8.dev5/json" in pypi_workflow
    assert "pypi-plan" in pypi_workflow
    assert "packages-dir: publish-dist/" in pypi_workflow
    assert "if: steps.pypi.outputs.upload == 'true'" in pypi_workflow
    assert "skip-existing" not in pypi_workflow
    assert '"!castlabs-v*"' in legacy_workflow
    assert (
        legacy_workflow.count(
            "if: ${{ !startsWith(github.ref, 'refs/tags/castlabs-v') }}"
        )
        >= 3
    )
    legacy_release = legacy_workflow[legacy_workflow.index("  release:\n") :]
    early_guard_start = legacy_workflow.index("Reject unsafe legacy publication")
    early_guard_end = legacy_workflow.index("Read version from file", early_guard_start)
    early_guard = legacy_workflow[early_guard_start:early_guard_end]
    assert early_guard_start < legacy_workflow.index("  tests-unix:\n")
    assert (
        "if: github.event_name == 'workflow_dispatch' && github.event.inputs.publish == 'true'"
        in early_guard
    )
    assert "startsWith(github.ref, 'refs/tags/')" not in early_guard
    assert "!startsWith(github.ref, 'refs/tags/castlabs-v')" in legacy_release
    assert "startsWith(github.ref, 'refs/tags/')" in legacy_release
    assert "github.ref == 'refs/heads/main'" in legacy_release
    assert 'test "$GITHUB_REF" = refs/heads/main' in legacy_release
    assert "manual legacy publishing accepts final X.Y.Z versions only" in (
        legacy_release
    )
    assert 'test "$VERSION" != 0.37.8.dev5' not in legacy_workflow
    assert legacy_workflow.count("final X.Y.Z versions only") == 2
    assert "tests/test_castlabs_release_tooling.py" in legacy_workflow
    shell_helpers_start = release_workflow.index("          download_existing() {")
    shell_helpers_end = release_workflow.index(
        "          trap cleanup_current_draft EXIT", shell_helpers_start
    )
    shell_helpers = textwrap.dedent(
        release_workflow[shell_helpers_start:shell_helpers_end]
    )
    subprocess.run(
        ["bash"],
        cwd=tmp_path,
        input=(
            "set -euo pipefail\n"
            f"{shell_helpers}\n"
            "touch empty-downloads empty-uploads\n"
            "download_existing empty-downloads downloaded\n"
            "upload_missing empty-uploads\n"
        ),
        text=True,
        check=True,
    )
    smoke = (ROOT / "tests" / "test_castlabs_release_smoke.py").read_text(
        encoding="utf-8"
    )
    smoke_gate = 'os.environ.get("CASTLABS_RELEASE_SMOKE_REQUIRED") != "1"'
    assert smoke_gate in smoke
    assert smoke.index(smoke_gate) < smoke.index("from c2pa import")
    assert release_workflow.count('CASTLABS_RELEASE_SMOKE_REQUIRED: "1"') == 2
    assert release_workflow.count("CASTLABS_RELEASE_EXPECTED_VERSION: 0.37.8.dev5") == 2
    assert "pytest.skip(" in smoke
    assert "unittest.skip" not in smoke
    dynamic_start = smoke.index(
        "def test_dynamic_assertion_builder_image_signing_round_trip():"
    )
    vsi_start = smoke.index(
        "def test_vsi_callback_recovery_explicit_iat_and_mfhd_round_trip():"
    )
    combined_start = smoke.index(
        "def test_dynamic_assertion_claim_signer_with_vsi_init_regression():"
    )
    fragmented_start = smoke.index("def test_fragmented_file_round_trip():")
    dynamic_test = smoke[dynamic_start:vsi_start]
    vsi_test = smoke[vsi_start:combined_start]
    combined_test = smoke[combined_start:fragmented_start]
    assert "def _exact_size_dynamic_assertion(reserve_size: int) -> bytes:" in smoke
    assert "assert len(content) == reserve_size" in smoke
    assert "_dynamic_claim_signer(dynamic_calls)" in dynamic_test
    assert 'FIXTURES / "A.jpg"' in dynamic_test
    assert ').sign(signer, "image/jpeg"' in dynamic_test
    assert "partial_claim" in dynamic_test
    assert '_read_clean_report("image/jpeg", signed)' in dynamic_test
    assert "_manifest_signer()" in vsi_test
    assert "_dynamic_claim_signer" not in vsi_test
    for required_operation in (
        "sign_init_segment",
        "sign_media_segment_at",
        "recovered.restore",
        "moof_sequence_number",
        "_assert_iat",
    ):
        assert required_operation in vsi_test
    assert "_dynamic_claim_signer(dynamic_calls)" in combined_test
    assert "assert len(content) == reserve_size == 64" in combined_test
    assert '_read_clean_report("video/mp4", signed_init)' in combined_test
    assert "assertion.bmffHash.mismatch" not in combined_test
    assert "_KnownDynamicAssertionVsiMismatch" not in smoke
    assert "pytest.mark.xfail" not in smoke
    assert "castlabs-v0.37.8.dev1" not in release_workflow
    assert "castlabs-v0.37.8.dev1" not in pypi_workflow
    assert "castlabs-v0.37.8.dev2" not in release_workflow
    assert "castlabs-v0.37.8.dev2" not in pypi_workflow
    assert "castlabs-v0.37.8.dev3" not in release_workflow
    assert "castlabs-v0.37.8.dev3" not in pypi_workflow
    assert "castlabs-v0.37.8.dev4" not in release_workflow
    assert "castlabs-v0.37.8.dev4" not in pypi_workflow
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "failed prerelease workflow run `34030865864`" in readme
    assert "No dev1 draft or GitHub release was created" in readme
    assert "failed prerelease workflow run `34057763620`" in readme
    assert "every installed-wheel test passed on Python 3.10 through 3.13" in readme
    assert "No dev2 draft or GitHub release survives" in readme
    assert "workflow emitted no exact root cause" in readme
    assert "not conclusively to the empty download-list loop" in readme
    assert "failed prerelease workflow run `34065998820`" in readme
    assert "every release-specific installed-wheel smoke passed" in readme
    assert "No dev3 draft or GitHub release was created" in readme
    assert "published `castlabs-v0.37.8.dev4` prerelease" in readme
    assert "immutable historical release artifacts and remain unchanged" in readme
    release_notes = (ROOT / "docs" / "release-notes.md").read_text(
        encoding="utf-8"
    )
    assert "## Version 0.37.8.dev5" in release_notes
    assert "Dev4 and earlier accepted\n  undersized callback outputs" in release_notes
    assert "breaking strictness\n  change" in release_notes


def test_cargo_execution_and_evidence_share_the_locked_command(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if "tree" in command:
            return SimpleNamespace(stdout=b"feature-report\r\n")
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    monkeypatch.setenv("CARGO_BUILD_JOBS", "1")
    monkeypatch.setenv("CARGO_INCREMENTAL", "0")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    report = tmp_path / "features-x86_64-unknown-linux-gnu.txt"
    release.command_cargo_build(
        SimpleNamespace(
            rust_root=str(tmp_path),
            target="x86_64-unknown-linux-gnu",
            feature_report=str(report),
        )
    )
    lock = release.load_lock()
    assert calls[0][0] == release.cargo_tree_command(lock, "x86_64-unknown-linux-gnu")
    assert calls[1][0] == release.cargo_command(lock, "x86_64-unknown-linux-gnu")
    assert report.read_bytes() == b"feature-report\n"

    facts_path = tmp_path / "facts.json"
    release.command_build_facts(
        SimpleNamespace(
            target="x86_64-unknown-linux-gnu",
            feature_report=str(report),
            epoch="1700000000",
            interpreter="Python 3.10.0",
            container=f"{release.MANYLINUX_IMAGE}@{release.MANYLINUX_DIGEST}",
            output=str(facts_path),
        )
    )
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    assert facts["cargoCommand"] == calls[1][0]
    assert facts["cargoTreeCommand"] == calls[0][0]
    assert facts["cargoBuildJobs"] == "1"
    assert facts["cargoIncremental"] == "0"
    assert facts["pythonHashSeed"] == "0"


def test_build_facts_requires_actual_reproducibility_environment(monkeypatch, tmp_path):
    report = tmp_path / "features.txt"
    report.write_text("features\n", encoding="ascii")
    monkeypatch.setenv("CARGO_BUILD_JOBS", "1")
    monkeypatch.setenv("CARGO_INCREMENTAL", "1")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    with pytest.raises(SystemExit, match="release evidence environment"):
        release.command_build_facts(
            SimpleNamespace(
                target="x86_64-unknown-linux-gnu",
                feature_report=str(report),
                epoch="1700000000",
                interpreter="Python 3.10.0",
                container=f"{release.MANYLINUX_IMAGE}@{release.MANYLINUX_DIGEST}",
                output=str(tmp_path / "facts.json"),
            )
        )


def _write_inputs(root: Path, reverse: bool, mtime: int) -> list[tuple[Path, str]]:
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    files = []
    for name, payload in (("z.bin", b"z" * 19), ("a.bin", b"a" * 7)):
        path = inputs / name
        path.write_bytes(payload)
        os.utime(path, (mtime, mtime))
        files.append((path, f"payload/{name}"))
    return list(reversed(files)) if reverse else files


def test_deterministic_tar_gzip_ignores_paths_order_and_mtimes():
    epoch = 1_700_000_000
    with (
        tempfile.TemporaryDirectory() as first,
        tempfile.TemporaryDirectory() as second,
    ):
        first_root = Path(first)
        second_root = Path(second)
        first_archive = first_root / "bundle.tar.gz"
        second_archive = second_root / "bundle.tar.gz"
        release.deterministic_tar_gz(
            first_archive, _write_inputs(first_root, False, int(time.time())), epoch
        )
        release.deterministic_tar_gz(
            second_archive, _write_inputs(second_root, True, 946_684_800), epoch
        )
        assert first_archive.read_bytes() == second_archive.read_bytes()
        assert first_archive.read_bytes()[3] & 0x08 == 0  # gzip FNAME is absent.
        with gzip.open(first_archive, "rb") as payload:
            with tarfile.open(fileobj=payload, mode="r:") as archive:
                assert archive.getnames() == ["payload/a.bin", "payload/z.bin"]
                for member in archive.getmembers():
                    assert member.mtime == epoch
                    assert member.uid == member.gid == 0
                    assert member.uname == member.gname == ""
                    assert member.mode == 0o644
        with pytest.raises(SystemExit):
            release.deterministic_tar_gz(
                first_archive, _write_inputs(first_root / "again", False, 0), epoch
            )


def test_packer_rejects_traversal_duplicates_and_symlinks():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "source"
        source.write_bytes(b"safe")
        output = root / "bundle.tar.gz"
        for name in ("../escape", "/absolute", "bad\\name"):
            try:
                release.deterministic_tar_gz(output, [(source, name)], 1_700_000_000)
            except SystemExit:
                pass
            else:
                raise AssertionError(f"accepted unsafe archive name {name!r}")
        try:
            release.deterministic_tar_gz(
                output,
                [(source, "same"), (source, "same")],
                1_700_000_000,
            )
        except SystemExit:
            pass
        else:
            raise AssertionError("accepted duplicate archive member")
        symlink = root / "link"
        try:
            symlink.symlink_to(source)
        except OSError:
            return
        try:
            release.deterministic_tar_gz(output, [(symlink, "link")], 1_700_000_000)
        except SystemExit:
            pass
        else:
            raise AssertionError("accepted symlink release member")


def test_safe_extract_round_trip_and_rejects_links():
    epoch = 1_700_000_000
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "input.bin"
        source.write_bytes(b"payload")
        bundle = root / "bundle.tar.gz"
        release.deterministic_tar_gz(bundle, [(source, "dir/input.bin")], epoch)
        destination = root / "output"
        args = type(
            "Args", (), {"archive": str(bundle), "destination": str(destination)}
        )
        release.command_extract(args)
        assert (destination / "dir" / "input.bin").read_bytes() == b"payload"

        unsafe = root / "unsafe.tar.gz"
        with tarfile.open(unsafe, "w:gz") as archive:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "target"
            archive.addfile(info)
        args = type(
            "Args",
            (),
            {"archive": str(unsafe), "destination": str(root / "unsafe-output")},
        )
        try:
            release.command_extract(args)
        except SystemExit:
            pass
        else:
            raise AssertionError("accepted archive symlink")

        with pytest.raises(SystemExit):
            release.command_extract(
                type(
                    "Args",
                    (),
                    {"archive": str(bundle), "destination": str(destination)},
                )
            )


def test_wheel_inspection_rejects_unsafe_and_multiple_native_members():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        wheel = root / "c2pa_python-0.37.8.dev5-py3-none-win_amd64.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("c2pa/libs/first.dll", b"one")
            archive.writestr("c2pa/libs/second.dll", b"two")
        try:
            release.wheel_details(wheel, "x86_64-pc-windows-msvc", "3.10")
        except SystemExit:
            pass
        else:
            raise AssertionError("accepted wheel with multiple native libraries")

        unsafe = root / "c2pa_python-0.37.8.dev5-py3-none-manylinux_2_28_x86_64.whl"
        with zipfile.ZipFile(unsafe, "w") as archive:
            archive.writestr("../libc2pa_c.so", b"unsafe")
        try:
            release.wheel_details(unsafe, "x86_64-unknown-linux-gnu", "3.10")
        except SystemExit:
            pass
        else:
            raise AssertionError("accepted unsafe wheel member")

        _write_wheel(
            unsafe,
            "x86_64-unknown-linux-gnu",
            b"native",
            extra_tag=True,
        )
        with pytest.raises(SystemExit, match="metadata tags must be exactly"):
            release.wheel_details(unsafe, "x86_64-unknown-linux-gnu", "Python 3.10.0")

        _write_wheel(
            unsafe,
            "x86_64-unknown-linux-gnu",
            b"native",
            graft=True,
        )
        with pytest.raises(SystemExit, match="unexpected auditwheel graft"):
            release.wheel_details(unsafe, "x86_64-unknown-linux-gnu", "Python 3.10.0")


def test_checksum_uses_artifact_basename():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "artifact.bin"
        path.write_bytes(b"artifact")
        expected = hashlib.sha256(b"artifact").hexdigest()
        output = Path(temp) / "artifact.bin.sha256"
        args = type("Args", (), {"artifact": str(path), "output": str(output)})
        release.command_checksum(args)
        assert output.read_text(encoding="ascii") == f"{expected}  artifact.bin\n"
        with pytest.raises(SystemExit):
            release.command_checksum(args)


def _write_wheel(
    path: Path,
    target: str,
    native: bytes,
    *,
    extra_tag: bool = False,
    graft: bool = False,
    line_ending: str = "\n",
    bom: bool = False,
    duplicate_name: bool = False,
    duplicate_version: bool = False,
) -> None:
    lock = release.load_lock()
    platform_tag = lock["targets"][target]["wheelPlatformTag"]
    native_name = lock["targets"][target]["library"]
    dist_info = f"c2pa_python-{release.RELEASE_VERSION}.dist-info"
    metadata_lines = [
        "Metadata-Version: 2.1",
        "Name: c2pa-python",
        f"Version: {release.RELEASE_VERSION}",
    ]
    if duplicate_name:
        metadata_lines.append("Name: adversarial-project")
    if duplicate_version:
        metadata_lines.append("Version: 999.0")
    metadata = (line_ending.join(metadata_lines) + line_ending).encode()
    wheel_metadata = (
        line_ending.join(
            [
                "Wheel-Version: 1.0",
                "Root-Is-Purelib: false",
                f"Tag: py3-none-{platform_tag}",
                *(["Tag: py3-none-any"] if extra_tag else []),
            ]
        )
        + line_ending
    ).encode()
    if bom:
        metadata = b"\xef\xbb\xbf" + metadata
        wheel_metadata = b"\xef\xbb\xbf" + wheel_metadata
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"c2pa/libs/{native_name}", native)
        if graft:
            archive.writestr("c2pa_python.libs/libcrypto.so", b"graft")
        archive.writestr(
            f"{dist_info}/METADATA",
            metadata,
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            wheel_metadata,
        )


def test_wheel_metadata_parser_handles_crlf_bom_and_rejects_duplicates(tmp_path):
    wheel = tmp_path / (f"c2pa_python-{release.RELEASE_VERSION}-py3-none-win_amd64.whl")
    _write_wheel(
        wheel,
        "x86_64-pc-windows-msvc",
        b"windows-native",
        line_ending="\r\n",
        bom=True,
    )
    details = release.wheel_details(wheel, "x86_64-pc-windows-msvc", "Python 3.10.0")
    assert details["file"] == wheel.name

    _write_wheel(
        wheel,
        "x86_64-pc-windows-msvc",
        b"windows-native",
        line_ending="\r\n",
        bom=True,
        duplicate_name=True,
    )
    with pytest.raises(SystemExit, match="package metadata is incorrect"):
        release.wheel_details(wheel, "x86_64-pc-windows-msvc", "Python 3.10.0")

    _write_wheel(wheel, "x86_64-pc-windows-msvc", b"windows-native")
    metadata_name = f"c2pa_python-{release.RELEASE_VERSION}.dist-info/METADATA"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr(
                metadata_name,
                "Metadata-Version: 2.1\n"
                "Name: c2pa-python\n"
                f"Version: {release.RELEASE_VERSION}\n",
            )
    with pytest.raises(SystemExit, match="duplicate wheel member"):
        release.wheel_details(wheel, "x86_64-pc-windows-msvc", "Python 3.10.0")

    _write_wheel(
        wheel,
        "x86_64-pc-windows-msvc",
        b"windows-native",
        duplicate_version=True,
    )
    with pytest.raises(SystemExit, match="package metadata is incorrect"):
        release.wheel_details(wheel, "x86_64-pc-windows-msvc", "Python 3.10.0")


def test_verified_wheel_native_is_exact_qualified_artifact(tmp_path):
    native = b"qualified-native-bytes"
    wheel = tmp_path / (
        f"c2pa_python-{release.RELEASE_VERSION}-py3-none-" "manylinux_2_28_x86_64.whl"
    )
    _write_wheel(wheel, "x86_64-unknown-linux-gnu", native)
    qualified = tmp_path / "libc2pa_c.so"
    qualified.write_bytes(native)
    output = tmp_path / "verified" / "libc2pa_c.so"
    release.command_verify_wheel_native(
        SimpleNamespace(
            wheel=str(wheel),
            target="x86_64-unknown-linux-gnu",
            native=str(qualified),
            output=str(output),
        )
    )
    assert output.read_bytes() == native

    qualified.write_bytes(b"different-qualified-native")
    with pytest.raises(SystemExit, match="differs from the qualified native"):
        release.command_verify_wheel_native(
            SimpleNamespace(
                wheel=str(wheel),
                target="x86_64-unknown-linux-gnu",
                native=str(qualified),
                output=str(tmp_path / "mismatch" / "libc2pa_c.so"),
            )
        )


def test_schema2_wheel_evidence_is_derived_from_final_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("CARGO_BUILD_JOBS", "1")
    monkeypatch.setenv("CARGO_INCREMENTAL", "0")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setenv("GITHUB_REPOSITORY", "local")
    lock = release.load_lock()
    epoch = 1_700_000_000
    source_sha = "a" * 40
    wheels = {}
    facts_paths = []
    native_payloads = {
        "x86_64-unknown-linux-gnu": b"linux-native-final",
        "x86_64-pc-windows-msvc": b"windows-native-final",
    }
    for target, native in native_payloads.items():
        wheel = tmp_path / (
            f"c2pa_python-{release.RELEASE_VERSION}-py3-none-"
            f"{lock['targets'][target]['wheelPlatformTag']}.whl"
        )
        _write_wheel(wheel, target, native)
        wheels[target] = wheel
        report = tmp_path / f"features-{target}.txt"
        report.write_text(f"features for {target}\n", encoding="ascii")
        facts = tmp_path / f"build-{target}.json"
        container = (
            f"{release.MANYLINUX_IMAGE}@{release.MANYLINUX_DIGEST}"
            if target == "x86_64-unknown-linux-gnu"
            else None
        )
        release.command_build_facts(
            SimpleNamespace(
                target=target,
                feature_report=str(report),
                epoch=str(epoch),
                interpreter="Python 3.10.0",
                container=container,
                output=str(facts),
            )
        )
        facts_paths.append(str(facts))

    bundle = tmp_path / (
        f"c2pa-python-{release.RELEASE_VERSION}-py3-none-wheels.tar.gz"
    )
    release.deterministic_tar_gz(
        bundle,
        [(wheel, wheel.name) for wheel in wheels.values()],
        epoch,
    )
    evidence_path = Path(f"{bundle}.evidence.json")
    release.command_evidence(
        SimpleNamespace(
            artifact=str(bundle),
            type="wheel-bundle",
            source_sha=source_sha,
            member=[f"{target}={wheel}" for target, wheel in wheels.items()],
            build_facts=facts_paths,
            output=str(evidence_path),
        )
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    release.validate_evidence(evidence, tmp_path, source_sha=source_sha)
    if importlib.util.find_spec("jsonschema") is not None:
        import jsonschema

        schema = json.loads(
            (ROOT / "release" / "castlabs-release-evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(evidence, schema)
        invalid_wheel = copy.deepcopy(evidence)
        invalid_wheel["artifact"]["members"][0].pop("pythonTag")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_wheel, schema)
        invalid_native_bundle = copy.deepcopy(evidence)
        invalid_native_bundle["artifact"]["type"] = "native-bundle"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_native_bundle, schema)
        native_member = {
            key: value
            for key, value in evidence["artifact"]["members"][0].items()
            if key not in {"pythonTag", "abiTag", "platformTag"}
        }
        member_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/$defs/member",
            "$defs": schema["$defs"],
        }
        jsonschema.validate(native_member, member_schema)
        native_member["pythonTag"] = "py3"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(native_member, member_schema)
    by_target = {member["target"]: member for member in evidence["artifact"]["members"]}
    for target, native in native_payloads.items():
        assert by_target[target]["nativeSha256"] == hashlib.sha256(native).hexdigest()

    native_evidences = [
        {
            "artifact": {
                "type": "native-bundle",
                "members": [
                    {
                        "target": target,
                        "nativeSha256": by_target[target]["nativeSha256"],
                    }
                ],
            }
        }
        for target in sorted(native_payloads)
    ]
    release.validate_release_evidence_consistency([evidence, *native_evidences])
    tampered_evidence = copy.deepcopy(native_evidences)
    tampered_evidence[0]["artifact"]["members"][0]["nativeSha256"] = "0" * 64
    with pytest.raises(SystemExit, match="different native digests"):
        release.validate_release_evidence_consistency([evidence, *tampered_evidence])

    by_target["x86_64-unknown-linux-gnu"]["nativeSha256"] = "0" * 64
    with pytest.raises(SystemExit):
        release.validate_evidence(evidence, tmp_path, source_sha=source_sha)


def _write_complete_release_assets(directory: Path) -> dict[str, Path]:
    directory.mkdir()
    result = {}
    for name in release.expected_release_asset_names():
        path = directory / name
        path.write_bytes(f"release asset {name}\n".encode())
        result[name] = path
    return result


def _release_json(paths: dict[str, Path], names: set[str], *, draft=True):
    return {
        "id": 77,
        "tag_name": release.RELEASE_TAG,
        "draft": draft,
        "prerelease": True,
        "name": release.RELEASE_NAME,
        "body": release.RELEASE_BODY,
        "target_commitish": TEST_SOURCE_SHA,
        "assets": [
            {
                "id": index + 100,
                "name": name,
                "size": paths[name].stat().st_size,
                "digest": f"sha256:{release.sha256_file(paths[name])}",
                "state": "uploaded",
            }
            for index, name in enumerate(sorted(names))
        ],
    }


def test_duplicate_release_records_fail_explicitly(tmp_path):
    path = tmp_path / "releases.json"
    release_record = {"id": 1, "tag_name": release.RELEASE_TAG}
    path.write_text(
        f"{json.dumps(release_record)}\n{json.dumps(release_record)}\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="multiple GitHub releases or drafts"):
        release.load_optional_json(path)


def test_draft_release_resume_requires_exact_existing_assets(tmp_path):
    assets = tmp_path / "assets"
    local = _write_complete_release_assets(assets)
    expected = set(local)
    assert len(expected) == 16
    assert {name for name in expected if name.endswith(".evidence.json.sha256")} == {
        f"c2pa-python-{release.RELEASE_VERSION}-py3-none-wheels.tar.gz.evidence.json.sha256",
        f"c2pa-python-{release.RELEASE_VERSION}-native-linux-x86_64.tar.gz.evidence.json.sha256",
        f"c2pa-python-{release.RELEASE_VERSION}-native-windows-x86_64.tar.gz.evidence.json.sha256",
    }

    new_plan = release.inspect_draft_release(assets, None, TEST_SOURCE_SHA)
    assert new_plan["releaseExists"] is False
    assert set(new_plan["missing"]) == expected

    existing_names = set(sorted(expected)[:4])
    prior_plan = release.inspect_draft_release(
        assets, _release_json(local, existing_names), TEST_SOURCE_SHA
    )
    downloaded = tmp_path / "downloaded"
    downloaded.mkdir()
    for name in existing_names:
        (downloaded / name).write_bytes(local[name].read_bytes())
    assert set(release.verify_draft_release(assets, downloaded, prior_plan)) == (
        expected - existing_names
    )
    (downloaded / sorted(existing_names)[0]).write_bytes(b"mismatch")
    with pytest.raises(SystemExit):
        release.verify_draft_release(assets, downloaded, prior_plan)

    complete_plan = release.inspect_draft_release(
        assets, _release_json(local, expected), TEST_SOURCE_SHA
    )
    complete_download = tmp_path / "complete-download"
    complete_download.mkdir()
    for name in expected:
        (complete_download / name).write_bytes(local[name].read_bytes())
    assert (
        release.verify_draft_release(
            assets, complete_download, complete_plan, require_complete=True
        )
        == []
    )

    published = _release_json(local, set(), draft=False)
    with pytest.raises(SystemExit):
        release.inspect_draft_release(assets, published, TEST_SOURCE_SHA)
    remote_mismatch = _release_json(local, {sorted(expected)[0]})
    remote_mismatch["assets"][0]["digest"] = f"sha256:{'0' * 64}"
    with pytest.raises(SystemExit):
        release.inspect_draft_release(assets, remote_mismatch, TEST_SOURCE_SHA)
    unexpected = _release_json(local, set())
    unexpected["assets"].append(
        {"id": 999, "name": "unexpected.bin", "size": 1, "state": "uploaded"}
    )
    with pytest.raises(SystemExit):
        release.inspect_draft_release(assets, unexpected, TEST_SOURCE_SHA)


def test_release_response_validators_cover_owned_empty_and_complete_states(tmp_path):
    assets = tmp_path / "assets"
    local = _write_complete_release_assets(assets)
    expected = set(local)

    discovery = release.inspect_draft_release(assets, None, TEST_SOURCE_SHA)
    assert discovery["releaseExists"] is False

    create_response = _release_json(local, set())
    minimally_parseable = copy.deepcopy(create_response)
    minimally_parseable["name"] = "strict validation will reject this name"
    response_path = tmp_path / "create-response.json"
    response_path.write_text(json.dumps(minimally_parseable), encoding="utf-8")
    extracted_id = tmp_path / "extracted-id.txt"
    release.command_extract_release_id(
        SimpleNamespace(release_json=str(response_path), id_output=str(extracted_id))
    )
    assert extracted_id.read_text(encoding="ascii") == f"{create_response['id']}\n"
    release_id = release.validate_release_identity(
        create_response, TEST_SOURCE_SHA, require_empty=True
    )
    assert release_id == create_response["id"]
    normalized_body = copy.deepcopy(create_response)
    normalized_body["body"] = normalized_body["body"].replace("\n", "\r\n") + "  \r\n"
    assert (
        release.validate_release_identity(
            normalized_body, TEST_SOURCE_SHA, require_empty=True
        )
        == release_id
    )
    for allowed_target in ("main", "feat/live-video-vsi", TEST_SOURCE_SHA):
        target_response = copy.deepcopy(create_response)
        target_response["target_commitish"] = allowed_target
        assert (
            release.validate_release_identity(
                target_response, TEST_SOURCE_SHA, require_empty=True
            )
            == release_id
        )
    for field, bad_value in (
        ("id", True),
        ("tag_name", "wrong-tag"),
        ("name", "wrong-name"),
        ("body", "wrong-body"),
        ("target_commitish", "b" * 40),
        ("draft", False),
        ("prerelease", False),
    ):
        invalid = copy.deepcopy(create_response)
        invalid[field] = bad_value
        with pytest.raises(SystemExit):
            release.validate_release_identity(
                invalid, TEST_SOURCE_SHA, require_empty=True
            )

    assert release.validate_owned_empty_draft(create_response, release_id) == release_id
    for field, bad_value in (
        ("name", "strict-name-mismatch"),
        ("target_commitish", "b" * 40),
    ):
        strict_mismatch = copy.deepcopy(create_response)
        strict_mismatch[field] = bad_value
        with pytest.raises(SystemExit):
            release.validate_release_identity(
                strict_mismatch, TEST_SOURCE_SHA, require_empty=True
            )
        assert (
            release.validate_owned_empty_draft(strict_mismatch, release_id)
            == release_id
        )
    for field, bad_value in (
        ("tag_name", "wrong-tag"),
        ("body", "ownership marker missing"),
        ("assets", [{"id": 9}]),
        ("draft", False),
    ):
        not_owned_empty = copy.deepcopy(create_response)
        not_owned_empty[field] = bad_value
        with pytest.raises(SystemExit):
            release.validate_owned_empty_draft(not_owned_empty, release_id)
    for invalid_id in (True, False, 0, -1, "0", "not-an-id"):
        with pytest.raises(SystemExit, match="positive integer"):
            release.positive_int(invalid_id, "test ID")
    with pytest.raises(SystemExit, match="expected GitHub release ID"):
        release.validate_release_identity(
            create_response,
            TEST_SOURCE_SHA,
            expected_release_id=True,
            require_empty=True,
        )

    exact_empty = copy.deepcopy(create_response)
    exact_plan = release.inspect_draft_release(
        assets,
        exact_empty,
        TEST_SOURCE_SHA,
        expected_release_id=release_id,
    )
    empty_download = tmp_path / "empty-download"
    empty_download.mkdir()
    assert (
        set(release.verify_draft_release(assets, empty_download, exact_plan))
        == expected
    )

    complete = copy.deepcopy(create_response)
    complete["assets"] = []
    for index, name in enumerate(sorted(expected), start=1000):
        response = {
            "id": index,
            "name": name,
            "size": local[name].stat().st_size,
            "digest": f"sha256:{release.sha256_file(local[name])}",
            "state": "uploaded",
        }
        assert release.validate_upload_response(response, local[name]) == index
        complete["assets"].append(response)

    digest_pending = copy.deepcopy(complete["assets"][0])
    digest_pending.pop("digest")
    assert (
        release.validate_upload_response(digest_pending, local[digest_pending["name"]])
        == digest_pending["id"]
    )

    sample_name = sorted(expected)[0]
    sample_response = complete["assets"][0]
    for field, bad_value in (
        ("id", True),
        ("id", 0),
        ("name", "wrong-name"),
        ("size", -1),
        ("digest", f"sha256:{'0' * 64}"),
        ("state", "new"),
    ):
        invalid = copy.deepcopy(sample_response)
        invalid[field] = bad_value
        with pytest.raises(SystemExit):
            release.validate_upload_response(invalid, local[sample_name])

    complete_plan = release.inspect_draft_release(
        assets,
        complete,
        TEST_SOURCE_SHA,
        expected_release_id=release_id,
    )
    complete_download = tmp_path / "complete-transition-download"
    complete_download.mkdir()
    for name, path in local.items():
        (complete_download / name).write_bytes(path.read_bytes())
    assert (
        release.verify_draft_release(
            assets,
            complete_download,
            complete_plan,
            require_complete=True,
        )
        == []
    )
    final_digest_missing = copy.deepcopy(complete)
    final_digest_missing["assets"][0]["digest"] = None
    with pytest.raises(SystemExit, match="digest differs"):
        release.inspect_draft_release(
            assets,
            final_digest_missing,
            TEST_SOURCE_SHA,
            expected_release_id=release_id,
        )


def _write_policy_wheels(directory: Path) -> dict[str, Path]:
    directory.mkdir()
    lock = release.load_lock()
    wheels = {}
    for target, target_data in lock["targets"].items():
        wheel = directory / (
            f"c2pa_python-{release.RELEASE_VERSION}-py3-none-"
            f"{target_data['wheelPlatformTag']}.whl"
        )
        _write_wheel(wheel, target, f"native-{target}".encode())
        wheels[wheel.name] = wheel
    return wheels


def _pypi_response(wheels: dict[str, Path], names: set[str]) -> dict:
    return {
        "info": {"name": "c2pa-python", "version": release.RELEASE_VERSION},
        "urls": [
            {
                "filename": name,
                "packagetype": "bdist_wheel",
                "digests": {"sha256": release.sha256_file(wheels[name])},
            }
            for name in sorted(names)
        ],
    }


def test_pypi_retry_plan_accepts_only_matching_existing_wheels(tmp_path):
    wheels_dir = tmp_path / "wheels"
    wheels = _write_policy_wheels(wheels_dir)
    names = set(wheels)
    _, missing = release.pypi_missing_wheels(wheels_dir, 404, None)
    assert set(missing) == names

    existing = {sorted(names)[0]}
    response = _pypi_response(wheels, existing)
    _, missing = release.pypi_missing_wheels(wheels_dir, 200, response)
    assert set(missing) == names - existing
    _, missing = release.pypi_missing_wheels(
        wheels_dir, 200, _pypi_response(wheels, names)
    )
    assert missing == []

    mismatch = copy.deepcopy(response)
    mismatch["urls"][0]["digests"]["sha256"] = "0" * 64
    with pytest.raises(SystemExit):
        release.pypi_missing_wheels(wheels_dir, 200, mismatch)
    unexpected = _pypi_response(wheels, existing)
    unexpected["urls"].append(
        {
            "filename": f"c2pa_python-{release.RELEASE_VERSION}.tar.gz",
            "packagetype": "sdist",
            "digests": {"sha256": "0" * 64},
        }
    )
    with pytest.raises(SystemExit):
        release.pypi_missing_wheels(wheels_dir, 200, unexpected)


def test_pypi_command_stages_all_missing_wheels_together(tmp_path):
    wheels_dir = tmp_path / "wheels"
    wheels = _write_policy_wheels(wheels_dir)
    existing = {sorted(wheels)[0]}
    response = tmp_path / "pypi.json"
    response.write_text(json.dumps(_pypi_response(wheels, existing)), encoding="utf-8")
    github_output = tmp_path / "github-output"
    destination = tmp_path / "publish"
    release.command_pypi_plan(
        SimpleNamespace(
            wheels_dir=str(wheels_dir),
            response=str(response),
            http_status="200",
            destination=str(destination),
            output=str(tmp_path / "plan.json"),
            github_output=str(github_output),
        )
    )
    assert {path.name for path in destination.iterdir()} == set(wheels) - existing
    assert github_output.read_text(encoding="utf-8") == "upload=true\n"
