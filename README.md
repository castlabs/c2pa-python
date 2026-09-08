# C2PA Python library

The [Castlabs c2pa-python repository](https://github.com/castlabs/c2pa-python) provides a Python library that can:

- Read and validate C2PA manifest data from media files in supported formats.
- Create and sign manifest data, and attach it to media files in supported formats.

Features:

- Create and sign C2PA manifests using various signing algorithms.
- Generate CBOR assertions at signing time with DynamicAssertion callbacks when supported by the native library.
- Sign C2PA 2.4 live-video Verifiable Segment Info (VSI) when supported by the native library.
- Sign and validate fragmented BMFF file sets when supported by the native library.
- Verify C2PA manifests and extract metadata.
- Add assertions and ingredients to assets.
- Examples and unit tests to demonstrate usage.

<div class="github-only">

For the best experience, read the docs on the [CAI Open Source SDK documentation website](https://opensource.contentauthenticity.org/docs/c2pa-c).

If you want to view the documentation in GitHub, see:
- [Using the Python library](docs/usage.md)
- [Supported formats](https://github.com/contentauth/c2pa-rs/blob/main/docs/supported-formats.md)
- [Configuring the SDK using `Context` and `Settings`](docs/context-settings.md)
- [Using Builder intents](docs/intents.md) to ensure spec-compliant manifests
- Using [working stores and archives](docs/working-stores.md)
- Selectively constructing manifests by [filtering actions and ingredients](docs/selective-manifests.md)
- [Diagram of public classes in the Python library and their relationships](docs/class-diagram.md)
- [Release notes](docs/release-notes.md)

</div>

## Prerequisites

This library requires Python version 3.10+.

## Package installation

Install the c2pa-python package from PyPI by running:

```bash
pip install c2pa-python
```

To use the module in Python code, import the module like this:

```python
import c2pa
```

## Building from local c2pa-rs sources

### Using a virtual environment with local builds

The `make` targets honor an active virtualenv. Create a virtual environment `./.venv` and activate it before running them so commands use the project interpreter rather than the global Python interpreter:

```sh
make create-venv && source .venv/bin/activate
```

### Build steps

By default the upstream-compatible build downloads a prebuilt native library from a [c2pa-rs](https://github.com/contentauth/c2pa-rs) release. To test the Python bindings against a local, unreleased c2pa-rs checkout, you can instead build the native library from source.

Prerequisites:

- A local clone of [the Castlabs c2pa-rs fork](https://github.com/castlabs/c2pa-rs) for VSI work, or the historical [Content Authenticity Initiative upstream](https://github.com/contentauth/c2pa-rs) for upstream-compatible builds.
- The [Rust toolchain](https://rust-lang.org/tools/install/) (`cargo` on your `PATH`).

Point `C2PA_RS_PATH` at your c2pa-rs checkout and run the `build-from-source` target:

```sh
export C2PA_RS_PATH=/path/to/c2pa-rs
make build-from-source C2PA_RS_PATH=$C2PA_RS_PATH
```

This does a clean build of the `c2pa-c-ffi` crate with the upstream-compatible `file_io` feature, stages the resulting library under both `artifacts/` and `src/c2pa/libs/`, and installs the package in editable mode, replacing any prebuilt artifacts from `make download-native-artifacts`. By default, the build uses the release profile; to build the debug profile instead, pass `EXTRA_BUILD_ARGS="--debug"`:

```sh
make build-from-source C2PA_RS_PATH=$C2PA_RS_PATH EXTRA_BUILD_ARGS="--debug"
```

When running the tests against an unreleased source build whose SDK version differs from `c2pa-native-version.txt`, explicitly provide the expected source version:

```sh
C2PA_SOURCE_BUILD_VERSION=0.91.0-dev python3 tests/test_unit_tests.py
```

The version test validates the loaded library against this value. When the variable is unset, it continues to validate downloaded release artifacts against `c2pa-native-version.txt`.

The source build honors `CARGO_TARGET_DIR`, which can keep temporary Cargo output outside the checkout. Native artifact downloads default to `contentauth/c2pa-rs`; set `C2PA_NATIVE_REPOSITORY=owner/repository` to use a compatible GitHub release repository without changing the default.

To build the paired experimental live-video fork, opt in explicitly:

```sh
export C2PA_FFI_FEATURES=file_io,unstable_live_video
make build-from-source C2PA_RS_PATH=$C2PA_RS_PATH
```

## Castlabs VSI prerelease process

The dedicated [`Castlabs VSI prerelease`](.github/workflows/castlabs-vsi-release.yml) workflow builds version `0.37.8.dev5` for Linux x86-64 and Windows x86-64. It does not call `scripts/download_artifacts.py`: both native libraries are compiled with Cargo `--locked` and `CARGO_BUILD_JOBS=1` from the exact [Castlabs c2pa-rs](https://github.com/castlabs/c2pa-rs) commit in [`release/castlabs-vsi-inputs.lock.json`](release/castlabs-vsi-inputs.lock.json). The lock also fixes the Rust 1.88.0 toolchain coordinated with c2pa-rs qualification, checksum-verified rustup installers, no-default-feature set, target set, and the Linux manylinux container digest. The legacy `build.yml` explicitly excludes `castlabs-v*` tag pushes and guards its jobs and PyPI publisher against manual dispatch on those tags; the dedicated workflow alone owns them. Ordinary non-Castlabs tag releases retain the legacy behavior, while manual legacy publication additionally requires `refs/heads/main` and a final `X.Y.Z` package version.

The immutable `castlabs-v0.37.8.dev1` tag records failed prerelease workflow run `34030865864`. Linux compiled successfully but its combined DynamicAssertion-plus-VSI smoke used a 5-byte callback result for a 64-byte reservation and later failed with `assertion.bmffHash.mismatch`; Windows compiled successfully and failed only in platform-sensitive wheel metadata parsing. The Linux failure was an undersized callback contract violation, not an inherent incompatibility between DynamicAssertions and VSI. No dev1 draft or GitHub release was created, and the tag remains unchanged.

The immutable `castlabs-v0.37.8.dev2` tag records failed prerelease workflow run `34057763620`. Both Linux and Windows builds succeeded, and every installed-wheel test passed on Python 3.10 through 3.13. Reconciliation logs ended after immediate list-based rediscovery following draft creation and before the created release ID was verified; the workflow emitted no exact root cause. The failure was therefore likely tied to eventual consistency or another dependency on that immediate list response, not conclusively to the empty download-list loop. No dev2 draft or GitHub release survives, and the tag remains unchanged. Dev3 captures the create response directly and moves immediately to exact-ID operations, removing that ambiguity.

The immutable `castlabs-v0.37.8.dev3` tag records failed prerelease workflow run `34065998820`. Both platform builds and every release-specific installed-wheel smoke passed on Linux and Windows with Python 3.10 through 3.13. Only the existing Windows Python 3.10 unit test `TestManagedResourceObjects.test_swapped_builder_is_freed_exactly_once` failed: native code consumed the original builder and reused its address for the replacement, so a post-close address count attributed the replacement free to the original handle. No dev3 draft or GitHub release was created, and the tag remains unchanged. Dev4 preserves the immediate post-swap no-free assertion, then checks only that idempotent close records exactly one free matching the replacement handle; a fake-handle regression covers deterministic same-address reuse.

The published `castlabs-v0.37.8.dev4` prerelease and its tag are immutable historical release artifacts and remain unchanged. Dev4 used the earlier maximum-size DynamicAssertion callback contract, which accepted outputs shorter than `reserve_size`. Dev5 intentionally makes that contract stricter: exact callback sizing is enforced for every signing path, and both undersized and oversized outputs are rejected.

Release controls:

- Configure `castlabs-v0.37.8.dev5` as a protected tag and require approval for the `castlabs-vsi-release` environment.
- A tag run accepts only that exact tag. A manual run accepts only a full 40-character SHA equal to the tip of `feat/live-video-vsi` and is build/test-only; draft release creation and provenance signing require the exact protected tag-triggered run.
- Source checkout URLs, full SHAs, package/native versions, and the pinned `Cargo.lock` SHA-256 are asserted before each build.
- The Linux wheel is built and repaired in the digest-pinned `manylinux_2_28_x86_64` image. Every wheel is tested without capability skips on clean Python 3.10 through 3.13; Python 3.10 also runs the broader unit and fragmented-file suites.
- Draft release creation happens only after both platform builds and all wheel tests. Every Action is pinned by full commit SHA, every bundle and evidence document has a SHA-256 sidecar, and all release files are individually covered by GitHub build provenance. The full REST create response provides the candidate ID; an immediate exact-ID GET must confirm the expected tag, draft state, empty assets, and normalized ownership marker before cleanup can be armed. Strict validation then checks prerelease state, name, normalized release identity text, and documented `target_commitish` forms. The immutable tag is independently resolved to the source SHA immediately before creation and final verification, so GitHub's ignored/defaulted `target_commitish` is never the source authority. A rerun may discover a prior draft by list only when exactly one match exists; after discovery, all queries, uploads, and downloads use the exact release or asset ID. Missing assets upload through the exact `uploads.github.com` release-ID endpoint without clobber. Immediate upload digests are checked when available; final success always requires exact API digests and downloaded byte equality. Published, mismatched, duplicate, or unexpected state fails. Cleanup uses only exact ID, tag, empty draft state, and ownership marker, and is disabled before the first upload, so response loss and all asset-bearing or reconciled drafts are preserved for manual inspection. The completed output remains a draft intentionally for operator finalization.
- [`Promote Castlabs VSI prerelease to PyPI`](.github/workflows/castlabs-vsi-pypi.yml) is a separate manual workflow protected by the `pypipublish` environment. It requires the finalized GitHub prerelease and verifies every wheel, bundle, evidence document, feature report, and checksum against provenance from the exact dedicated signer workflow, tag, and source SHA. Checksums and strict evidence then validate the final-wheel metadata and embedded native digests before promotion.
- PyPI does not provide a multi-file transaction. Promotion therefore queries the version JSON API first. A fresh release uploads both platform wheels together; a retry accepts an existing wheel only when PyPI's SHA-256 exactly matches the local attested wheel, then uploads all missing wheels together. A mismatched or unexpected PyPI file fails. This policy intentionally publishes no source distribution for the two-platform prerelease and safely recovers from an unavoidable prior partial wheel upload.

Intermediate Actions artifacts expire after seven days. A draft resume always rebuilds both platforms and requires byte-identical output for every already-uploaded asset; rerunning only an expired release job cannot recover its inputs, so rerun the complete tag workflow. If reproducibility or an operator mistake leaves a mismatched prior draft, the workflow preserves it and reports failure. Inspect it manually, then remove only that draft with `gh release delete castlabs-v0.37.8.dev5 --repo castlabs/c2pa-python --yes` before rerunning the complete protected-tag workflow. Never use clobber to repair a mismatch.

`tests/test_castlabs_release_smoke.py` is intentionally gated for ordinary contributors because upstream native binaries do not provide every Castlabs capability. Bare pytest skips that module unless `CASTLABS_RELEASE_SMOKE_REQUIRED=1` is set. The dedicated wheel-test jobs always set it; with the gate enabled, package version, dynamic assertions, fragmented files, VSI callback signing, recovery, explicit time, and MFHD probing are hard assertions with no capability skip. Contributors with a qualified installed wheel can run the same gate explicitly with `CASTLABS_RELEASE_SMOKE_REQUIRED=1 python -m pytest -q tests/test_castlabs_release_smoke.py`. `CASTLABS_RELEASE_EXPECTED_VERSION` exists only for testing an already-built prior candidate during release-pipeline repair; the dedicated tagged workflow explicitly fixes it to dev5.

At the pinned c2pa-rs commit, VSI initialization signs through `Builder::from_shared_context`, so it inherits DynamicAssertions registered on the Context's claim signer. The common Python callback bridge enforces `reserve_size` as the exact serialized CBOR size for every signing path. The earlier `assertion.bmffHash.mismatch` came from returning only 5 bytes for a 64-byte reservation; it was not an inherent DynamicAssertion-plus-VSI incompatibility. The release smoke now returns valid exact-size CBOR, requires clean Reader validation for both standalone image and combined VSI init signing, and exercises combined media signing and recovery without an xfail.

The release bundle/evidence implementation is shared across Linux and Windows in `scripts/castlabs_release.py`. Cargo execution and recorded evidence use the same generated command, including the locked manifest, target, no-default-features flag, and feature list. Evidence generation reads and requires the actual `CARGO_BUILD_JOBS=1`, `CARGO_INCREMENTAL=0`, and `PYTHONHASHSEED=0` environment rather than merely recording constants. Each final wheel must have one exact platform tag, contain no auditwheel `.libs/` graft, and embed native bytes identical to the qualified Rust output. The platform native bundles are then constructed from those extracted final-wheel bytes, and complete-set validation requires the wheel and native-bundle evidence digests to agree. The helper rejects unsafe or duplicate archive members and refuses to replace outputs; sorted tar archives normalize ownership, permissions and timestamps, and gzip headers omit FNAME. Schemas and their committed lock live in `release/`. Historical upstream release links and behavior remain available through the Content Authenticity Initiative references elsewhere in this README and in `docs/release-notes.md`.

### Note on targets for macOS

On macOS this produces a universal (arm64+x86_64) library by default, which requires both Rust targets:

```sh
rustup target add aarch64-apple-darwin x86_64-apple-darwin
```

To build a single-architecture library instead, set `C2PA_LIBS_PLATFORM` to a specific platform (for example `aarch64-apple-darwin`).

## Live-video VSI signing

`has_live_video_vsi()` reports the base experimental API;
`has_live_video_vsi_callbacks()`, `has_live_video_vsi_recovery()`, and
`has_live_video_vsi_explicit_time()` report the base API together with the
respective additive callback, artifact-recovery, or explicit-time symbol.
`has_live_video_vsi_mfhd_probe()` independently reports the additive stateless
BMFF sequence probe; `moof_sequence_number()` reads a media segment's unsigned
`moof/mfhd.sequence_number` without creating a VSI session. When available,
`LiveVideoVsiSession` signs initialization and media segment bytes using either
a 32-byte local Ed25519 session-key seed or a purpose-aware Ed25519/ES256
callback suitable for non-exportable keys. Signed init and last-media artifacts
can restore a callback-backed session without invoking the key. See
[Using the Python library](docs/usage.md#live-video-vsi-signing).

## Dynamic assertions

`has_dynamic_assertions()` reports whether the loaded native library contains the Castlabs DynamicAssertion extension. When available, `Signer.add_dynamic_assertion()` registers a callback that receives the partial claim during signing and returns valid CBOR assertion bytes exactly equal to `reserve_size`; the common callback bridge enforces this for every signing path. Required padding belongs in semantic assertion fields such as CAWG `pad1` or `pad2`, never as trailing bytes. Standard upstream native binaries remain importable, but calling this method with one raises `C2paError.NotSupported`. See [Using the Python library](docs/usage.md#dynamic-assertions).

## Fragmented BMFF file sets

`has_fragmented_files()` reports whether the loaded native library contains the Castlabs fragmented file APIs. When available, `Builder.sign_fragmented()` signs an initialization segment and its media-fragment glob, while `Reader.from_fragmented_files()` validates the signed file set. Standard upstream native binaries remain importable; unavailable operations raise `C2paError.NotSupported`. See [Using the Python library](docs/usage.md#fragmented-bmff-file-sets).

## Examples

See the [`examples` directory](https://github.com/castlabs/c2pa-python/tree/feat/live-video-vsi/examples) for some helpful examples:

- `examples/read.py` shows how to read and verify an asset with a C2PA manifest.
- `examples/sign.py` shows how to sign and verify an asset with a C2PA manifest.
- `examples/training.py` demonstrates how to add a "Do Not Train" assertion to an asset and verify it.

## API reference documentation

Documentation is published at [github.io/c2pa-python/api/c2pa](https://contentauth.github.io/c2pa-python/api/c2pa/index.html).

To build documentation locally, refer to [this section in Contributing to the project](https://github.com/contentauth/c2pa-python/blob/main/docs/project-contributions.md#api-reference-documentation).

## Contributing

Contributions are welcome!  For more information, see [Contributing to the project](https://github.com/contentauth/c2pa-python/blob/main/docs/project-contributions.md).

## License

This project is licensed under the Apache License 2.0 and the MIT License. See the [LICENSE-MIT](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-MIT) and [LICENSE-APACHE](https://github.com/contentauth/c2pa-python/blob/main/LICENSE-APACHE) files for details.
