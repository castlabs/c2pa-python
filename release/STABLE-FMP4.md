# Stable fMP4 Hotfix Release

This lane is independent of the live-video VSI lane. It keeps the Python stable
runtime from `e00831db`, with true-merged Python ladder PR #2 and separately
reviewed native single-file ladder, cleanup, segmented refusal and legacy TFRA
fixes on the stable baseline. It does not merge VSI APIs or change
crypto providers.

| Contract | Value |
| --- | --- |
| Python package | unreleased `c2pa-python==0.31.0+stardustproof.6` |
| Reserved tag name (not created) | `castlabs-v0.31.0+stardustproof.6` |
| Release context | `castlabs-stable-fmp4` |
| Profile ID | `stable-fmp4-v1` |
| Native SDK/FFI | `0.80.0` |
| Python release branch | `fix/stable-single-file-fmp4` |
| Native build | defaults enabled; `--features file_io` |
| Crypto | baseline vendored OpenSSL, not `rust_native_crypto` |
| Platforms | Linux x86-64 manylinux_2_28 and Windows x86-64 |
| Wheel tests | Python 3.10, 3.11, 3.12, 3.13, both platforms |
| Evidence | schema 2, standard shape, no VSI capability inference |

## Approval Gate

The `.6` candidate is release preparation only. Python PR #2 head
`1fa22786f38b74d4205d959d4dcb86121b77f88a` was true-merged onto stable base
`75378c15eb84ee79b8ffcac4564b10873a87f41f` at merge
`4ec85a282038726831adcf468bfdf3c26a918a2d` in
`integration/stable-ladder-python-release-r4`.
The final reviewed/qualified native handoff is:

- Commit: `75f6df217e9bdd11a82e62b42ae550b7d91e9d04`.
- Cargo.lock SHA-256: `e42129cab9c33fec6f748878d7738ee5dc5ead4537c86512ae654282a68fcc94`.
- Native runtime version: `0.80.0`; Rust: `1.88.0`.

That native commit is on Castlabs `fix/stable-single-file-fmp4`. Python
release-profile builds and the eight installed-wheel matrix cells have **not**
been qualified for `.6` yet. Uncommitted preparation sources cannot pass
`validate-sources`. Do not create tags, releases or publication API calls during
this preparation. Published `.5` facts, assets, evidence and tag are immutable.

### Historical Release Facts

The previous `.3` candidate run
[`35862631757`, attempt 2](https://github.com/castlabs/c2pa-python/actions/runs/35862631757)
passed both platform builds and all installed-wheel tests at Python source
`44437a5ca56e6e921cd116ce04db7cc7fd786b0c`. Its reserved tag
`castlabs-v0.31.0+stardustproof.3` remains fixed at that source and was **never
published as a release**. The unescaped `+` in its Actions tag filter prevented
the release run from starting. Do not delete, move, reuse, or publish that tag.
The `.4` repair uses a single-quoted filter with one literal backslash before
`+`; exact event refs, evidence and asset names retain the unescaped `+`.
The `.4` source is `c916e8a82df97f740dd05ec58911dd02ea58325d`, but that build
lacks the legacy TFRA correction and must not be used or republished. Published `.5`
retains the corrected literal tag filter and advanced only the reviewed stable
native pin and gates. Regenerate affected assets from unsigned masters.

For the published `.5` release, the native audit cleared this committed/pushed source in
`castlabs/c2pa-rs`, canonical branch `fix/stable-single-file-fmp4`:

- Commit: `589174898eca4c2c42289d3251c0619420806f43`.
- Cargo.lock SHA-256: `fc10bef635df091377d02cfa9f1597462aa016c3db3439d43451a3b93c37edcf`.
- Native runtime version: `0.80.0`.

The branch consolidation preserves the native commit already shipped in `.5`;
it is not a new release or a change to the published release evidence.

- Stable consolidation: https://github.com/castlabs/c2pa-rs/pull/4.
- Upstream TFRA: https://github.com/contentauth/c2pa-rs/issues/2709 and https://github.com/contentauth/c2pa-rs/pull/2710.
- Upstream fMP4: https://github.com/contentauth/c2pa-rs/issues/2714 and https://github.com/contentauth/c2pa-rs/pull/2715.

The current `.6` handoff pins are recorded in `castlabs-stable-fmp4-inputs.lock.json` and the
helper's `RUST_COMMIT` / `CARGO_LOCK_SHA256` constants. The Python `c2pa-rs` gitlink
points to the same commit; `.gitmodules` uses the canonical Castlabs HTTPS URL.
Future pin changes must update all three together after review. Negative tests
remove approval only via explicit in-memory monkeypatches; missing approvals,
changed source pins and null lock entries still fail closed.

Do not substitute the old baseline or the modern VSI SHA, and do not regenerate
Cargo.lock during release. The workflow
reads the native checkout ref only from this validated lock; there is no native
SHA workflow input or automatic upstream binary fallback.

The lock is the explicit release profile. Consumers select `stable-fmp4-v1` by
reviewed release facts with `releaseContext: castlabs-stable-fmp4`, then match the
exact Python/native source and Cargo.lock pins, artifact URLs and digests, native
version, requested feature list and real resolved feature report. They must not
infer this profile from a version prefix, a missing VSI capability, or a smoke
skip. Artifact evidence retains the standard schema-2 keys:
`schemaVersion`, `artifact`, `sources`, `builds`, `runner`, `workflow`.
The context/profile identifiers live in the approved lock and downstream release
facts, not new ad-hoc fields in the artifact evidence.

## Build And Acceptance

Both platform builds must execute all 10 focused Rust
`asset_handlers::bmff_io::tfra_tests` with Rust 1.88.0, `--locked`, defaults and
`file_io`. The `cargo-tfra-tests` helper requires the exact test names to pass
with zero failures or ignored tests, not merely Cargo exit status. These include
the no-`moov` legacy writer/XMP/placeholder synthetics; the existing single-file
Merkle wheel smokes bypass that legacy path and are not TFRA qualification.
The diagnosis, original per-entry fix and unchanged fixture are credited to
BibinBaby444. The historical TFRA backport leaves the single-file Merkle implementation
unchanged and does not repair already corrupted TFRA tables: regenerate affected
assets from the unsigned master.

Both platform builds additionally run `cargo-ladder-tests` before native staging:
10 exact `assertions::bmff_hash::single_file_ladder_tests` (including cleanup
replacement preservation), four exact `store::tests::test_fragmented_refuses_`
tests, one FFI `sign_ladder` and six FFI `sign_fragmented` tests on Linux,
five on Windows because the directory-alias regression is Unix-only. The totals
are 21 on Linux and 20 on Windows. Each focused
suite requires its exact names, count, zero failures and zero ignores. Zero-test
success, duplicate/wrong records or tampered summaries fail closed. These use
Rust 1.88.0, release profile, `--locked`, defaults and requested only `file_io`;
no native VSI tests are selected.

The workflow is `.github/workflows/castlabs-stable-fmp4-release.yml`. Pushes to
the exact `fix/stable-single-file-fmp4` branch run non-publishing candidate builds,
so the lane can be qualified without registering it on the default branch. Manual
dispatch from `fix/stable-single-file-fmp4` accepts that branch-tip `source_sha`,
which must also match the workflow's `GITHUB_SHA`, and builds/tests candidates
without publication. Dispatch from the default branch or a tag is rejected
before checkout. Only a **push** of exact `castlabs-v0.31.0+stardustproof.6` enters the protected
`castlabs-stable-fmp4-release` publication environment. This is a GitHub artifact
release with `prerelease=false`, not a PyPI upload (the package has a local version).
The legacy workflows explicitly refuse this version/tag.

Native builds use the pinned Rust 1.88.0 toolchain and manylinux image, Cargo
`--locked`, default features enabled, and the baseline vendored OpenSSL profile.
Linux installs the required full Perl modules; Windows requires the runner's
Strawberry Perl via `OPENSSL_SRC_PERL`. Actual `cargo tree --edges features` output
is published as `features-<target>.txt` and its digest appears in build evidence.
The SDK report must include OpenSSL, HTTP reqwest/blocking, thumbnails and file IO;
the FFI report must include default/http/add_thumbnails/file_io. VSI and
rust-native crypto features are rejected.
The requested evidence feature list is exactly `["file_io"]`; HTTP and thumbnails
are enabled only by the unchanged defaults, not extra requested flags.

The actual Linux Cargo 1.88.0 report is preserved without changes in
`tests/fixtures/stable-fmp4/features-x86_64-unknown-linux-gnu.txt` for regression
tests (not as release evidence). It confirms that `http` exists on the FFI line,
while SDK `c2pa v0.80.0` has `http_reqwest` and `http_reqwest_blocking` instead.
The sibling signer consumer originally required an SDK `http` token and rejected
this report. Its validator now checks the real SDK/FFI names, and a read-only
cross-repo probe accepts the unmodified actual report in the consumer's synthetic
schema-2 fixture. No native defaults or report bytes were changed to achieve
acceptance. This checks the contract, not approval of real release artifacts.

`CASTLABS_STABLE_RELEASE_TARGET` makes `setup.py` consume only the staged native
artifact for that exact host target. Missing staged bytes are fatal. It never
invokes Cargo or a downloader in this mode. The final audited wheel must contain
the exact qualified library bytes, canonical package metadata and wheel tag,
complete SHA-256 RECORD coverage, and the correct ELF64/PE32+ x86-64 architecture.
Unexpected auditwheel grafts, symlinks, traversal, duplicate members or metadata,
and digest mismatches fail. Both final wheels and both native bundles are bound
by schema-2 source/lock/build evidence, feature reports, and checksum sidecars.

`tests/test_castlabs_release_smoke.py` always executes real Python/native APIs.
It has no environment opt-in, capability skips, mocks, or xfails:

- Ordinary `Builder.sign()` on a single file assembled from the committed
  synthetic `tests/fixtures/tiny-segmented` init and two media fragments.
- Raw JUMBF/CBOR checks for the BMFF Merkle map, `initHash`, fragment `count`, and
  one decoded C2PA Merkle proof UUID per moof, with correct IDs and locations.
- Exact preservation of both mdat payloads and clean native validation.
- Tampering in the later fragment must produce `assertion.bmffHash.mismatch`.
- Real DynamicAssertion callback execution through ordinary JPEG signing.
- Real `Builder.sign_fragmented()` / `Reader.from_fragmented_files()` round-trip,
  payload preservation, and later-fragment tamper rejection.

Only fixture credential trust is excluded from the content-validity verdict;
signature, content, and assertion failures remain fatal. No customer inputs,
secrets, ffmpeg installation, or timestamp service are needed by these smokes.
The ordinary upstream tests additionally run on Python 3.10 on each platform.
Every Python 3.10-3.13 installed-wheel cell on both platforms also runs
`tests/test_builder_sign_ladder.py` with `C2PA_REQUIRE_SIGN_LADDER=1` and `cbor2`.
The real round-trip verifies byte-identical embedded/returned manifests, two
Merkle maps, unchanged sources and native validation of both outputs. Missing
symbol or `cbor2` is fatal before signing. Synthetic parser tests cover the
eight-byte Merkle offset and JUMBF Label Present (`0x02`, not Requestable `0x01`).

The stable loader has `C2PA_LIBRARY_NAME` and standard package/LD_LIBRARY_PATH
search locations, but **no `C2PA_LIBRARY_PATH` override**. This lane does not change
the runtime loader. Installed-wheel CI starts from a clean venv and verifies the
package/native versions before acceptance. CI clears source/library environment
overrides and asserts that both package and binding paths belong to the clean
venv, with the native library loaded from that wheel's package directory.

## Publication Safety

All requested platform builds and installed-wheel tests must succeed before any
GitHub draft is created. Publication checks the immutable tag against the exact
Python SHA. Draft reconciliation uses exact release IDs, source SHA, marker,
name, stable flag, and a closed asset-name set. Reused assets must have matching
GitHub SHA-256 digests and are also downloaded by exact asset ID for byte checks.
Missing API digests fail closed. Uploads are no-clobber, exact-ID REST calls;
asset names are URL-encoded (including the local-version `+`).

After upload, all assets are re-queried and verified, then checked again immediately
before publication. The complete asset-ID/digest snapshot must be unchanged.
Only then is the exact release ID PATCHed to `draft=false`. The response identity,
IDs and digests are verified and the tag is checked again. Cleanup can delete
only a newly created, validated, still-empty owned draft before the first upload;
reconciled drafts, ambiguous API responses, drafts with assets and published
releases are preserved. Failed/ambiguous publication requires operator inspection,
never destructive retry cleanup.

## Local Checks

Tooling tests do not load c2pa and use clearly synthetic pins only in test memory:

```bash
python3 -m pytest -q tests/test_castlabs_release_tooling.py
python3 scripts/castlabs_release.py validate-lock
```

Both commands must now succeed. Full `validate-sources` additionally requires a
committed, clean Python checkout whose gitlink and immutable event SHA match the
lock; uncommitted Python edits cannot qualify for release.

### Current Development Probes

Local Python 3.12 probes built a development wheel through PEP 517 from this
checkout and installed it into a new isolated venv. All four mandatory smokes,
28 required ladder/fragmented tests, and 244 unit tests passed (276 total).
The earlier unit-suite HTTP-resolver failure did not recur; TSA was not disabled.
Tests ran from an empty external directory without source/library overrides,
with `C2PA_REQUIRE_SIGN_LADDER=1` and installed version
`0.31.0+stardustproof.6`. Dependencies were installed only in the isolated venv.

The native build source was the clean stable integration at
`75f6df217e9bdd11a82e62b42ae550b7d91e9d04`. Its build used a separate shared
Cargo target cache; the cache-containing worktree's HEAD does not identify the
build source. The staged and installed native bytes matched:

`/root/opencode-worktrees/c2pa-rs-ladder-source-r2/target-r2/debug/libc2pa_c.so`

SHA-256: `2f881744ae2f6ef9faec06a449ac66568e8062657c250fc3c6031fe78de4671b`.

These probes resolve the earlier shared-venv metadata-smoke failure without
bypassing it. They use a debug native and a `py3-none-linux_x86_64` development
wheel, not a manylinux release artifact or release-profile qualification. No tag,
release or publication was performed.

The release-profile native commands required on their respective platforms are:

```bash
python scripts/castlabs_release.py cargo-ladder-tests \
  --rust-root ../c2pa-rs --target x86_64-unknown-linux-gnu
python scripts/castlabs_release.py cargo-ladder-tests \
  --rust-root ../c2pa-rs --target x86_64-pc-windows-msvc
```

They are configured and tested against complete and malformed outputs, but were
not run as local release builds: the supplied existing cache contains debug
artifacts only. Remote nonpublishing qualification remains outstanding after the
coordinator commits clean Python sources and pushes the native handoff.

### Historical Local Probes

The following are earlier `.3` development probes, not `.6` qualification.
Post-audit Linux qualification executed all four mandatory smokes successfully using
this worktree's editable `.3` candidate install and the rebuilt native
library at `/root/opencode-worktrees/c2pa-rs-stable-fmp4/target/debug/libc2pa_c.so`,
SHA-256 `4bbaf1078fdd7b005b7d28cf49234c6e29714abcf5cc5aa027c2c18895c98094`.
The synthetic tiny-segmented fixture works for both ordinary single-file and
segmented signing; no replacement media was needed. This is a real-native test,
not installed platform-wheel qualification. The stable signer-info constructor
requires bytes, so the tests initialize `ta_url=b""` then set the native field to
NULL to disable external timestamp requests.

A local `py3-none-linux_x86_64` wheel was then rebuilt through staged-only
packaging using those exact bytes and the approved lock, installed into
`target/wheel-smoke-venv`, and tested from an empty working directory with
`C2PA_LIBRARY_NAME`, `C2PA_LIBRARY_PATH`, `PYTHONPATH`, and `LD_LIBRARY_PATH` unset.
All four mandatory smokes passed again. The loaded library was the wheel's own
`site-packages/c2pa/libs/libc2pa_c.so`, with the same SHA-256 as the staged input;
the wheel's RECORD hashes and sizes were checked. An isolated copy of the wheel's
bindings with the native library omitted failed import, rather than falling back
to a source-worktree or system library. These local probes are repeatable with
`python3 target/check_local_wheel.py` while the local artifacts remain available.

This debug-native development wheel is **not** the manylinux release candidate or
schema-2 release evidence. Packaging uses
`CASTLABS_STABLE_RELEASE_TARGET=x86_64-unknown-linux-gnu` and never rebuilds or
downloads native bytes. Approval of source pins does not replace clean-source
validation or release-profile build evidence. Windows, both release-profile
wheels and the full release workflow remain outstanding.

Local qualification can be repeated without a native rebuild or fake release pin:

```bash
python3 -m venv --system-site-packages target/python-smoke-venv
target/python-smoke-venv/bin/python -m pip install --no-build-isolation --no-deps -e .
PYTHONDONTWRITEBYTECODE=1 \
C2PA_LIBRARY_NAME=/root/opencode-worktrees/c2pa-rs-stable-fmp4/target/debug/libc2pa_c.so \
target/python-smoke-venv/bin/python -m pytest -q tests/test_castlabs_release_smoke.py
```

For the current candidate, after installing its wheel and `pytest`, `cbor2`:

```bash
C2PA_REQUIRE_SIGN_LADDER=1 python -m pytest -q \
  tests/test_castlabs_release_smoke.py tests/test_builder_sign_ladder.py
```
