# Upstream Integration Baseline

Baseline-only Python integration, tested 2026-09-10. Functional trusted-VSI
bindings are deliberately not implemented or enabled. This is not release
qualification and does not change immutable dev5 source/version/artifact facts.

Subsequent checkpoint: native `e0f980ec` fixes the purpose-isolation blocker
recorded below. The unchanged `TestSettings` plus scaffold ABI checks passed
56 tests and 6 subtests in 1.15s on that baseline. The historical results below
remain unchanged; ongoing functional Python work is documented separately in
`trusted-vsi-python-contract.md` and does not use the disabled scaffold contract.

## Scope And Pairing

- Python worktree: `/root/opencode-worktrees/c2pa-python-trusted-vsi-functional`.
- Python starting commit: `0d48e6a09b9d627dcf6385e3e591be8086e9af1f`.
- Native library: `/root/opencode-worktrees/c2pa-rs-trusted-vsi-functional/target/debug/libc2pa_c.so`.
- Native reported version: `0.91.0-dev`, integrating ContentAuth `312491af0e3e9fb5b3ba604d86ef44194ab580d9`.
- Native worktree HEAD at inspection: `cee86aae03887b5a0dddcd765a39e96360963bb0`;
  integrated native changes were not yet committed. A later native review/rebuild
  must be qualified again; these results do not certify that future binary.
- Tested library SHA-256: `10e6bf5d17d707f7e25d11eba69bce23318d12679a2c7b39046b8d5cdd43eaea`.
- Tested library size: 280930096 bytes; mtime `2026-09-10 13:32:02.274382637 +0200`.

Every native-backed command used:

```sh
env PYTHONPATH=/root/opencode-worktrees/c2pa-python-trusted-vsi-functional/src \
  C2PA_LIBRARY_NAME=/root/opencode-worktrees/c2pa-rs-trusted-vsi-functional/target/debug/libc2pa_c.so \
  C2PA_SOURCE_BUILD_VERSION=0.91.0-dev \
  C2PA_TRUSTED_VSI_ABI_REQUIRED=1 \
  python3 -m pytest ...
```

No native builds, global pip changes, wheel/sdist builds, publication, commits,
or pushes were performed. `python3 setup.py egg_info` generated ignored metadata
under `src/c2pa_python.egg-info` with the existing `0.37.8.dev5` Python version
solely to run the opt-in smoke tests from source. Otherwise installed metadata
reported unrelated version `0.31.0`. No new native binary was copied or packaged
under a dev5 artifact name.

## Changes

Exact edited files:

- `src/c2pa/c2pa.py`: `Settings.update` documents native additive trust merging
  and fresh-settings/context removal semantics; no new FFI bindings or runtime
  trust rewriting.
- `docs/context-settings.md`: typed manifest/CAWG/TSA configuration, explicit
  memberships, additive updates, removal semantics, and qualification warning.
- `tests/trust_config_test_settings.json`: original bundle retained byte-for-byte
  in manifest and TSA entries; original global EKU policy retained. No new roots,
  CAWG membership, allowed-list, revocation fetch, or verification bypass.
- `tests/test_unit_tests.py`: fixture membership digests, additive/removal and
  purpose-isolation regressions; correct four ingredient MIME arguments and add
  an explicit mismatch-rejection regression.
- `docs/upstream-integration-baseline.md`: this qualification record.

The nine-certificate legacy bundle hashes to
`f3de5e4ea3213319eedc5e3890f0ff615bf0e754323ffd20dcca8a3f1c5ab921`.
The unchanged EKU text hashes to
`174983a609d76784c4ef5e2621740bf32fb615f88412d94f4fc26670365a9b81`.

## Compatibility Findings

1. Legacy thread-local `load_settings` with `trust.trust_anchors` returned `Valid`
   instead of the original expected `Trusted` for `C.jpg`. Explicit `Context`
   still converted the legacy field successfully. Typed entries fix the legacy
   test path while keeping all original trust assertions intact. TSA membership
   is explicit so new timestamps retain the original bundle authorization.
2. Native ingredient parsing now rejects JPEG bytes declared as `image/png`,
   raising `Other: asset could not be parsed: invalid header` with PNG/JPEG magic
   bytes in the message. Four multiple-ingredient/resource tests used `A.jpg`
   with a PNG MIME. They now declare `image/jpeg`, retaining the same assets and
   operations. A separate negative test retains coverage of the rejected input.
   Reader MIME autodetection tests remain unchanged and passed.
3. Native settings merges are additive, including changed entries sharing a
   `trust_uri`; `anchors: []` does not remove existing entries. Fresh settings
   plus a new context remove trust without mutating existing contexts. Tested
   with actual native readers, not mocked settings.
4. **Open native security blocker:** a fresh context containing only a `cawg`
   anchor or only a `tsa` anchor for the fixture root still reports `C.jpg` as
   `Trusted`, including `signingCredential.trusted`, no failure codes, and the
   supplied trust-list URI. No manifest-purpose anchor was supplied. The new
   `TestSettings.test_settings_typed_trust_purposes_do_not_authorize_other_roles`
   preserves the expected `Valid` result for those two cases and currently fails
   both subtests. It is not skipped or xfailed. This blocks qualification of
   purpose isolation; Python must not hide or relabel native validation results.

Native evidence for item 4 (read-only inspection): `sdk/src/store.rs:166-198`
loads every purpose into the same certificate trust policy;
`sdk/src/crypto/cose/certificate_trust/openssl.rs:34` iterates all anchor sets;
`sdk/src/crypto/cose/verifier.rs:311-325` logs `signingCredential.trusted` for a
successful result without rejecting the returned non-manifest anchor type.
The Rust-native backend also iterates all sets. Native remediation belongs to
the native owner, not this Python baseline change.

## Test Evidence

Commands below were run from the Python worktree with the pairing environment
above. Durations are pytest wall times. No old-library capability skips were
introduced; the paired trusted-VSI scaffold checks ran against the real library.

| Command / selection | Result | Seconds |
|---|---|---:|
| `--collect-only -q` before changes | 613 tests collected | 0.94 |
| `tests/test_unit_tests.py::TestSettings tests/test_unit_tests.py::TestReader::test_stream_read_get_validation_state_with_trust_config tests/test_trusted_vsi_api.py` before fixture migration | 53 passed, 1 legacy trust failure | 0.68 |
| `--ignore=tests/test_unit_tests_threaded.py --durations=20 -o faulthandler_timeout=120` after fixture migration | 555 passed, 4 ingredient MIME failures, 73 subtests passed; release-smoke module opt-in skip | 504.99 |
| `tests/test_unit_tests_threaded.py -k 'not TestContextualBuilderWithThreads' --durations=15 -o faulthandler_timeout=120` | 41 passed, 13 assigned to next partition | 190.74 |
| `tests/test_unit_tests_threaded.py -k TestContextualBuilderWithThreads --durations=15 -o faulthandler_timeout=120` | 13 passed, 41 already covered | 159.19 |
| `tests/test_unit_tests.py -k 'TestSettings or add_multiple_ingredients or rejects_mismatched_format' --durations=10` after MIME fixes and new regressions | 16 test methods passed; 2 purpose-isolation subtests failed, 4 subtests passed | 11.00 |
| `tests/test_castlabs_release_smoke.py --durations=10` with additional `CASTLABS_RELEASE_SMOKE_REQUIRED=1` | 5 passed, no skips | 1.29 |
| `tests/test_trusted_vsi_api.py tests/test_castlabs_release_smoke.py tests/test_castlabs_release_tooling.py tests/test_unit_tests.py::TestC2paSdk --durations=5` with additional `CASTLABS_RELEASE_SMOKE_REQUIRED=1` | 70 passed, no skips | 2.76 |

The original suite's failures were rerun after correction; all original tests
have passing coverage across these runs. The newly added purpose-isolation
regression remains failing. The release-smoke module's initial opt-in skip was
subsequently exercised explicitly, not accepted as qualification evidence.

Timeout allowances: non-threaded 600 seconds; threaded partitions 600 and 480
seconds. Neither partition timed out. Process inspection found no concurrent
native build/test jobs before starting the long runs. Slowest tests were
non-threaded sign-all-files (83.02s / 71.08s) and threaded async sign-all-files
(79.97s / 58.87s), consistent with these tests' live TSA requests. Tests retained
their original network behavior and contention workloads.

The trusted-VSI surface remains disabled: Python capability helpers return
false and the paired native scaffold ABI returns disabled outputs. Functional
bindings must wait for the separately assigned functional ABI and qualification.
The native library SHA-256 was unchanged at the final check. `git diff --check`
passed; only the five files listed above are modified/untracked.
