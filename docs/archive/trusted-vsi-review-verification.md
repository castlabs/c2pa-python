# Trusted VSI Review Verification

Archived verification/provenance, not the product contract or authorization to
merge, repin, label or dispatch CI. See the current
[Python contract](../trusted-vsi-python-contract.md) for the deliberate integration
hold. Historical counts below precede the subsequent review follow-ups.

## Earlier Pairings

The former product-contract status described qualification against the
consolidated functional native from `castlabs/c2pa-rs`
`feat/trusted-vsi-functional` (`0.92.0-dev`, Rust 1.96.0, mask 63). The current
workflow pin `6b506352800c8225cf5564ce99c726aaa71039f4` is `203dc08d`
(ContentAuth main `69907b5a` merged) plus CI-only fixes: rustls `0.23.45` /
rustls-webpki `0.103.15` for RUSTSEC-2026-0285, test-only lint scopes, a feature
gate on a crate-private helper and rustdoc, with no C ABI/capability change.
The Python source integrates `Builder.sign_ladder` and carries unreleased
identity `0.37.13.dev0`.

The `203dc08d` pairing was qualified at Python
`5c64f2cc090eeb29506bc766faa69b959e4ed982` by hosted Linux/Windows paired run
`castlabs/c2pa-python` Actions `36793704783`: focused 186, ladder harness,
non-threaded 730, threaded 54, installed-wheel 186. Qualification of the
`6b506352` pairing was recorded on castlabs/c2pa-python#4 by run ID. These
pairings do not qualify the new state-v3/input contract.

Earlier native `5c186c07` (debug library SHA-256
`dc79e81a084fc7b25e12423539b137f24d69693da46cb0166cb04538bd5589f9`) at Python
`941c2ad5b57d23f31dbabf9fbef4776878cf630c`: local Linux focused 179,
ladder harness, non-threaded 714, threaded 54, installed-wheel 179 passed;
hosted Linux/Windows paired run `36671268428` passed on both. Local
qualification-only artifacts (never published):
`c2pa_python-0.37.13.dev0-py3-none-linux_x86_64.whl` SHA-256
`8731d135ce2c1db61b061e1f2c76272a55b9f7e7e2e2ea8769b10b5fd4a8707f`, sdist
`e846e5688d07bcf5959885c0c1728afde4ec89bbb7cf2b80a665956056b8b5ab`.
The earlier `0.37.9.dev0` artifacts paired with native `3569fb86` are historical
only. Immutable dev5 release inputs/artifacts are unchanged.

## Initial Local Review

Python worktree: `fix/trusted-vsi-review-python`, base
`12d265db92e8dcbf80b8255278e9a7fc5945f750`, uncommitted review changes.
Native input: `/root/opencode-worktrees/c2pa-rs-trusted-vsi-review-native`,
uncommitted step2 changes atop `d6e7b529581a4dfc0fd5585773d246ee2c191378`.
Only the cdylib was built, reusing the existing
`/tmp/opencode-v1.18.29/opencode/trusted-review-native-target` with Rust 1.96.0,
one Cargo job, incremental disabled, dev debug info disabled, and features
`rust_native_crypto,http,add_thumbnails,file_io,unstable_live_video`.
The loaded `debug/libc2pa_c.so` reports `0.92.0-dev`, mask 63, SHA-256
`149f4b250a5d697e38355a3f3f08ce1abf61c7e2b0418175153f690a456eb357`.
This records a local binary, not a new native pin or published revision.

The initial frozen-source tests used these selections without an editable install:

```sh
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
export C2PA_LIBRARY_NAME=/tmp/opencode-v1.18.29/opencode/trusted-review-native-target/debug/libc2pa_c.so
export C2PA_SOURCE_BUILD_VERSION=0.92.0-dev C2PA_TRUSTED_VSI_ABI_REQUIRED=1
export C2PA_REQUIRE_SIGN_LADDER=1 C2PA_REQUIRE_FRAGMENTED_FILES=1
python3 -m pytest -q tests/test_trusted_vsi_api.py tests/test_fragmented_files.py tests/test_sign_ladder.py tests/test_native_ownership.py tests/test_native_ownership_opaque.py tests/test_trusted_vsi_build.py -ra
python3 -m pytest -q -ra --ignore=tests/test_unit_tests_threaded.py -o faulthandler_timeout=120
python3 -m pytest -q tests/test_unit_tests_threaded.py -ra -o faulthandler_timeout=120
```

Initial results: focused 228 passed / 11 subtests; non-threaded 750 passed /
128 subtests / one module skip; threaded 54 passed. The skip is the existing
release-smoke module requiring an explicitly qualified installed wheel; no wheel
qualification or immutable dev5 evidence is claimed. An earlier run during edits
had four source-introspection subtest failures from changed source line offsets;
the frozen-source rerun passed them without changing those assertions.
Both `tests/ladder_native.py` candidate and stock harnesses passed.

Stock compatibility used the official ContentAuth `c2pa-v0.91.0` Linux x86-64
release library (SDK `0.91.0`, SHA-256
`dfa68d2a8ee739bb75919dcb5300f2cb289e1b51ecce94b0f339ff287ebe0703`), which lacks
dynamic-assertion registration, ladder signing and live-video callback exports.
With `C2PA_LIBRARY_NAME=/tmp/opencode-v1.18.29/opencode/python-review-stock/lib/libc2pa_c.so`,
`C2PA_SOURCE_BUILD_VERSION=0.91.0`, and required-capability flags unset:
`pytest -q tests/test_trusted_vsi_api.py tests/test_sign_ladder.py tests/test_fragmented_files.py tests/test_native_ownership.py -k 'not paired' -ra`
passed 117 / skipped 19 / deselected 70. Exactly four skips are the scripted
dynamic wrapper cases; required qualification makes that missing export fail.
The same stock library passed 101 lifecycle/object/fork tests plus 49 subtests
(the two ManagedResource unit classes and ManagedResourceForkGuard).
Actual-native Builder callback-close subprocesses run in the stock lane too.
The initially suggested prior packaged library reports `0.80.0` and lacks the
required `c2pa_reader_crjson` export, so it was not stock-0.91 evidence.

## Native Status Compatibility

Read-only inspection of
`6b506352800c8225cf5564ce99c726aaa71039f4:c2pa_c_ffi/src/live_video.rs` confirmed
`pub blocked: bool` at line 214, native conversion `blocked: rust.blocked()` at
line 616, and the offset-18 assertion at line 2035. The Python status fix fills
the missing bridge, not a missing native field in the actual workflow pin.
Arbitrary same-version/mask library identity remains a step3 concern, not a
demonstrated missing-`blocked` ABI mismatch against `6b506352`.

## Review Follow-Up Checks

The follow-up changed Python preflight/admission cleanup, documentation and
tests only. No native build, installation, full-suite rerun, target modification
or artifact cleanup was performed. The preserved step2 cdylib still has SHA-256
`149f4b250a5d697e38355a3f3f08ce1abf61c7e2b0418175153f690a456eb357`.
Focused pytest used `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src` and
`-p no:cacheprovider`; small generated fixtures used fresh, explicitly owned
`python-review-followups-20261007-v*` scratch directories under the approved temp
root. The native target was never used as scratch or changed.

With the preserved step2 library and the required-capability flags from the
initial local section:

```sh
python3 -m pytest -q -p no:cacheprovider --basetemp=/tmp/opencode-v1.18.29/opencode/python-review-followups-20261007-v3 tests/test_trusted_vsi_api.py tests/test_fragmented_files.py tests/test_sign_ladder.py tests/test_native_ownership.py tests/test_native_ownership_opaque.py tests/test_trusted_vsi_build.py -ra
```

Result: **241 passed / 11 subtests, no skips**. New coverage includes Context
close inside a context-signing Builder callback, two admitted bookkeeping guards
with staggered drain, CLOSED-pending `_release_handle()` preservation, logical
Signer close before preflight vs during admission, interrupted admission with
exception identity, and non-consuming bad-format preflight. The subprocess
lifetime proof has a bounded 90-second timeout. These checks do not authorize
concurrent native operations or establish generic thread safety.

With the official stock `0.91.0` library/path from the initial local section,
`C2PA_SOURCE_BUILD_VERSION=0.91.0` and required-capability flags unset:

```sh
python3 -m pytest -q -p no:cacheprovider --basetemp=/tmp/opencode-v1.18.29/opencode/python-review-followups-20261007-v4 tests/test_trusted_vsi_api.py tests/test_sign_ladder.py tests/test_fragmented_files.py tests/test_native_ownership.py tests/test_trusted_vsi_build.py -k 'not paired' -ra
python3 -m pytest -q -p no:cacheprovider tests/test_unit_tests.py::TestManagedResourceObjects tests/test_unit_tests.py::TestManagedResourceLifecycle tests/test_unit_tests_threaded.py::TestManagedResourceForkGuard -ra
```

Results: **148 passed / 19 capability skips / 70 deselected**, including the
renamed non-native CI-gate test; **101 passed / 49 subtests** for stock
lifecycle/object/fork checks. The stock subprocess proof now also covers closing
Context inside the signing callback.

Selective older-library compatibility used
`C2PA_LIBRARY_NAME=/tmp/opencode-v1.18.29/opencode/libc2pa_c-203dc08d.so`,
`C2PA_SOURCE_BUILD_VERSION=0.92.0-dev`, and `C2PA_TRUSTED_VSI_ABI_REQUIRED=1`:

```sh
python3 -m pytest -q -p no:cacheprovider tests/test_trusted_vsi_api.py -k 'callback_exception_identity_blocked_state_and_durable_retry or reentrant_close_native_subprocess or value_wrappers_are_frozen_and_v1_layouts_exact' -ra
```

Result: **7 passed / 140 deselected**. This older artifact reports `0.92.0-dev`
and mask 63, SHA-256
`0401bf3da2060fbdae3223ec0feb926f836b59604d9d4fe9c993122e29d5b6fe`.
The checks exercise healthy/failed `blocked` status, exact layout and actual
native callback-close paths without requiring state version 3. The artifact's
filename is not an embedded revision attestation. The read-only `6b506352`
source inspection above independently confirms that the actual CI pin writes
`blocked`. Neither narrow compatibility evidence nor the older artifact's
version/mask qualifies the new state-v3 contract. Repin/integration, the deferred
step3 revision probe, hosted paired qualification and any maintainer CI label
remain on hold; no merge-readiness claim is made.

## Final Admission Review

The final follow-up documents the deliberate foreign-PID restriction on guarded
admission, not a universal SDK fork ban. It adds rejection-before-lock/FFI and
pending consumed-teardown regressions, clarifies `_release_handle()`'s deferred
semantics, and explains why Builder keeps both close points. No runtime guard
policy was broadened, native files changed, or native/full-suite builds run.

The admission test follows the existing PID-simulation convention: an inherited
lock fails if touched, an FFI spy must not run, and rejection must leave the
handle, callback pins and lifecycle unchanged without release/free. No actual
fork fixture exists in the current suites, so no actual-fork subprocess proof is
claimed. The consumed teardown test requests `free_handle=False` inside an
admitted bookkeeping guard, preserves the False pending decision and pins until
exit, then requires one release and zero native frees.

With the preserved step2 library, `C2PA_SOURCE_BUILD_VERSION=0.92.0-dev`,
`C2PA_TRUSTED_VSI_ABI_REQUIRED=1`, `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH=src`:

```sh
python3 -m pytest -q -p no:cacheprovider tests/test_trusted_vsi_api.py -k 'call_guard or admitted_call_guards or release_handle or consumed_teardown_inside or teardown_copies or scripted_reentrant_close or reentrant_close_native_subprocess' -ra
```

Result: **17 passed / 132 deselected**, with no new disk-backed fixture outputs.

## Final Source Regression

After the review follow-ups, an independent frozen-source run used the same
patched native library above, Python 3.12, `PYTHONDONTWRITEBYTECODE=1`,
`PYTHONPATH=src`, `C2PA_SOURCE_BUILD_VERSION=0.92.0-dev`, and all four required
functional capability flags. The final run on 2026-10-07 passed:

- non-threaded source suite: **765 passed, 128 subtests passed, one module skip**;
- threaded source suite: **54 passed**;
- `git diff --check`: passed.

The module skip is the installed-release smoke described above, not a skipped
trusted-VSI capability. No installed-wheel or hosted qualification is claimed.
The first independent runner omitted `C2PA_SOURCE_BUILD_VERSION`, making the
version test compare this `0.92.0-dev` source-build library with the stock
`0.91.0` artifact pin. The runner was corrected to use the same explicit source
version as paired CI; no product code or version assertion was weakened.

The preserved same-key init-epoch probe also passed all six cases against this
patched library and binding. It is compatibility evidence, not a lifecycle or
counter-carry implementation.
On official stock `0.91.0` with its library selection and required flags unset,
the same selection prefixed by `not paired and (...)` passed **15 / deselected
134**. The unchanged stock lifecycle/object/fork command above passed **101 /
49 subtests** again. These focused selections overlap prior evidence; their
counts must not be summed as unique qualification. Native integration/repin,
the step3 revision probe and hosted qualification remain pending.
