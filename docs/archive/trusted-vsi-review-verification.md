# Trusted VSI Review Verification

Archived verification/provenance, not the product contract or authorization to
merge, repin, label or dispatch CI. See the current
[Python contract](../trusted-vsi-python-contract.md) for the deliberate integration
hold. Historical counts below precede the subsequent review follow-ups.

The revision-3 gate was added after the Python review merge `71d7cf9` on
`qualification/trusted-vsi-integrated-review`. Earlier results below predate that
gate: neither SDK `0.92.0-dev` nor mask 63 identifies a trusted-VSI contract.
The preserved step2 cdylib `149f4b25...` and older workflow pairing lack the new
stateless revision probe and now fail closed before operational ABI binding.
References below to a deferred step3 probe describe the historical review, not
the current Python contract. Final committed-native/hosted qualification remains
pending; the integrated local revision-3 qualification is recorded below.

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

## Revision Gate Stock Checks

After merge `71d7cf9`, the integrated Python worktree adds the exact revision-3
gate. No native build was performed; the preserved step2 cdylib lacks the probe,
so real paired tests await the native agent's final library handoff. The workflow
pin, build helper and build metadata are unchanged. No commit, push, repin, CI
label or dispatch was performed for this gate.

Using the official stock `0.91.0` library at
`/tmp/opencode-v1.18.29/opencode/python-review-stock/lib/libc2pa_c.so`,
`C2PA_SOURCE_BUILD_VERSION=0.91.0`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src`,
and all four required-capability flags unset:

```sh
python3 -m pytest -q -p no:cacheprovider --basetemp=/tmp/opencode-v1.18.29/opencode/python-contract-revision-stock-20261007 tests/test_trusted_vsi_api.py tests/test_sign_ladder.py tests/test_fragmented_files.py tests/test_native_ownership.py tests/test_trusted_vsi_build.py -k 'not paired' -ra
python3 -m pytest -q -p no:cacheprovider tests/test_unit_tests.py::TestManagedResourceObjects tests/test_unit_tests.py::TestManagedResourceLifecycle tests/test_unit_tests_threaded.py::TestManagedResourceForkGuard -ra
```

Results: **208 passed / 19 expected stock capability skips / 70 deselected**;
**101 passed / 49 subtests passed**. The trusted-VSI-only non-paired selection
passed **133 / four expected dynamic-registration skips / 70 deselected** and
overlaps the broader command. Mocked raw-loader subprocesses verify that missing
or non-3 revisions cannot bind or call operational trusted ABI despite matching
SDK/symbol/mask claims. They also cover wrong SDK versions, missing symbols,
partial/unknown masks, exact revision-3 probe ordering, early constructor/helper
rejection and independent ordinary/legacy callback binding. Both required flags
are tested to make paired-fixture revision diagnostics fail, never skip. These
are scripted/stock compatibility checks, not real revision-3 native qualification.

## Integrated Revision-3 Qualification

Local Linux/Python 3.12 qualification on 2026-10-07 used
`qualification/trusted-vsi-integrated-review`, HEAD
`71d7cf958a41be0f40c2a350b7bcdd6027b55170`, plus the uncommitted revision-gate
changes. The supplied native library was built separately from native integrated
HEAD `859a8584e13c7767e16fe12257e3ad69523ed7cf` plus the uncommitted revision
probe. No native build was performed by this Python qualification runner.
Preflight required SDK `0.92.0-dev`, exact contract revision 3, mask 63 and all
six Python availability probes true against
`/tmp/opencode-v1.18.29/opencode/trusted-review-native-target/debug/libc2pa_c.so`.
Its SHA-256 was
`585464e737b5affd580bdf203b53920cff77075cf89e92b81c3661a9918b1950`, checked again
at completion. This is local binary provenance, not an embedded commit identity
or a final native pin.

The first installed run found a test-only assumption in the raw-loader matrix:
its subprocess forced the checkout's `src/` even in an installed-wheel lane,
where no source-local library is staged. `test_trusted_vsi_api.py` now selects
the parent's actual package directory and asserts the child imports that same
binding file. Production code and qualification gates were not changed. A
separate first ladder child had transient Python-startup `ENOMEM` while scanning
an unrelated editable-package path on `/mnt/c`; the identical harness passed
on retry. The original logs/artifacts were retained in
`/tmp/opencode-v1.18.29/opencode/python-revision3-qualification-20261007/`.

Final frozen-source results, rerun in a fresh directory after the test fix:

| Lane | Result |
|---|---|
| Actual-native focused source (trusted VSI, fragmented, ladder, ownership, opaque ownership, build tooling) | 301 passed, 11 subtests passed |
| Candidate ladder harness with native integrated `sdk/tests/fixtures` | Passed signing, shared-manifest/tamper, path-refusal and callback-lifecycle checks |
| Installed-wheel functional qualifier | 283 passed, 11 subtests passed |
| Installed-wheel release smoke | 5 passed |
| Full non-threaded source, including release smoke | 828 passed, 128 subtests passed; 39 existing deprecation warnings |
| Full threaded source | 54 passed |
| `git diff --check` | Passed |

There were **no skips or deselections** in these final lanes. Counts overlap and
must not be summed as unique qualification. Source runs used
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<worktree>/src`, the explicit library
above, `C2PA_SOURCE_BUILD_VERSION=0.92.0-dev`, and all four flags set to `1`:
`C2PA_TRUSTED_VSI_ABI_REQUIRED`, `C2PA_TRUSTED_VSI_FUNCTIONAL_REQUIRED`,
`C2PA_REQUIRE_SIGN_LADDER`, `C2PA_REQUIRE_FRAGMENTED_FILES`.

The existing build helper created qualification-only `0.37.13.dev0` artifacts
using the explicit library. The existing qualifier created a fresh isolated venv
with system dependencies and installed the wheel with `--no-deps`; the runner
set `PIP_NO_INDEX=1`. Installed identity checks proved both `c2pa` and its bundled
library reside under that venv, with no `PYTHONPATH`, `C2PA_LIBRARY_NAME`,
`LD_LIBRARY_PATH` or `DYLD_LIBRARY_PATH` overrides. The bundled library hash,
revision, mask and all six probes were checked. Installed binding bytes matched
the source binding SHA-256 below. Only after installed qualification passed did
the full source lanes enable `CASTLABS_RELEASE_SMOKE_REQUIRED=1` with
`CASTLABS_RELEASE_EXPECTED_VERSION=0.37.13.dev0`, using the venv interpreter for
matching distribution metadata while explicitly selecting the frozen source and
reviewed native library. This is not immutable dev5 release evidence.

Final evidence root:
`/tmp/opencode-v1.18.29/opencode/python-revision3-qualification-20261007-v2/`.
It contains `status.json` (all final steps successful), `runner.log`,
`preflight.log`, `source-focused.log`, `ladder-candidate.log`, `build.log`,
`installed-focused.log`, `installed-identity.log`, `installed-release-smoke.log`,
`source-metadata.log`, `source-nonthreaded.log`, `source-threaded.log`,
`source-before.json`, `source-after.json`, `source-before.patch`, and
`dist/functional-build.json`. The before/after source snapshots were identical
through qualification; this archive section was appended afterward.

| Qualified input/artifact | SHA-256 |
|---|---|
| Uncommitted source patch snapshot (`source-before.patch`) | `166cb29c578081a9046ac5413569a8de5ff5f3ec9646a2bbfd063a90350dcf48` |
| Source/installed `c2pa.py` | `928ffc0871bf49fd8bf805c7a672499b6ea7de4cba3844968dd5832f684925bb` |
| `tests/test_trusted_vsi_api.py` | `eadf6f0088b71285e7cd8c36caff47af8fdaac4cf0a710a68058a6ccf63eca89` |
| `dist/c2pa_python-0.37.13.dev0-py3-none-linux_x86_64.whl` | `1b04b29aaf921f17bf3d81899e81101f10c4958c8224e3d541e86373158eb20e` |
| `dist/c2pa_python-0.37.13.dev0.tar.gz` | `dd290b7b4aec9e0af61b1fe12980770e1d0c5f9720f832df88bcecca0a2b1b8f` |

No build-helper metadata fact or public revision getter was added. No native
build, other-worktree edit, pin/workflow change, commit, push, CI label or
dispatch occurred. Nothing was staged. Final native commit integration/repin and
hosted qualification remain separate authorized work.

## Segmented ABR Init-Glob Integration Fix

On 2026-10-07 the signer integrated caller at
`src/stardustproof_c2pa_signer/manifest.py:2431` was inspected read-only. It calls
`Builder.sign_fragmented` with keywords `signer`, `asset_path` (a staged
`*/init` glob), `fragments_glob` (init-relative), and `output_dir`. Python's
literal-file/glob ban prevented this native-supported operation before FFI.
Only that filesystem preflight was removed; text/path-like, UTF-8, empty/NUL,
capability, ownership, callback and admission checks are unchanged. There is no
compatibility shim, alternate native path, per-rendition signing loop, new API,
descriptor JSON, filepath alias or source/output policy relaxation.

### Native Contract Proof

Read-only inspection used clean native integrated HEAD
`a6d4cdcc05638ee8dd0afce7fa5c850d7031a80c`, tree
`f8335291eb744790c10fc71000e5b6116f95e213`:

- `c2pa_c_ffi/src/c_api.rs:2436-2551`: `reserve_fragmented_output` expands the
  native init glob, joins fragment globs to each init parent, checks empty matches
  and flattened-name collisions, rejects existing rendition output entries, then
  exclusively reserves output directories and init files. Reservation/signing
  failures can leave partial outputs; there is no automatic cleanup.
- `c2pa_c_ffi/src/c_api.rs:2554-2627`: the public six-argument C ABI accepts an
  init path/glob, fragment glob and output root, passes the DA-aware borrowed
  signer to `sign_fragmented_files`, then returns manifest bytes read from the
  first output through the Builder Context. No multi-asset descriptor mode is
  necessary. Python continues to use this exact ABI.
- `sdk/src/builder.rs:3483-3551`: `Builder::sign_fragmented_files` documents
  multi-init globs and passes the expanded paths to a single Store operation.
- `sdk/src/store.rs:2982-3271`: `save_to_bmff_fragmented` validates fragment
  matches, flattened layouts and source/output separation, assigns a distinct
  `uniqueId`/`localId` pair to each rendition, and signs one shared manifest.
  The Rust SDK allows existing non-source output inits; the C/Python ABI does
  **not** inherit that overwrite allowance, because its reservation preflight
  rejects existing rendition directories.
- `docs/archive/vsi-consolidation-merges.md:74-82` records integration of #17's
  glob-aware, exclusively reserved FFI contract, superseding the older literal
  compatibility shape. Native tests `fragmented::sign_bunny_segmented_renditions`
  and `fragmented::rejects_collisions_before_writes` at
  `c2pa_c_ffi/src/c_api.rs:3994` and `:4091` corroborate the documented contract;
  those native tests were inspected, not rerun here.

| Inspected native/SDK file | SHA-256 |
|---|---|
| `c2pa_c_ffi/src/c_api.rs` | `024e069363f1ff16cb3392afaf66bdeaeb5c415498d903a3ed3d440dfa3e546a` |
| `sdk/src/builder.rs` | `b4de95c42eeac9a80d251e16c30a9535bacd2abafcef9bfd68a89ecba7f66ff3` |
| `sdk/src/store.rs` | `d30fa3b8b8c02728fbd084feff28af3b809f1299f143b5a44a5ce33283c8beb2` |

These three files are unchanged between `859a8584` and `a6d4cdcc`. The supplied
binary's earlier build provenance is `859a8584` plus the then-uncommitted
revision probe, as recorded above. The probe was subsequently committed in
`a6d4cdcc`; inspecting the current clean tree is not a claim that an embedded
version/probe attests that commit, nor an independent reconstruction of the
original build. No native source, target, library or ABI was changed in place,
and no native build or new target prefix was used.

### Python Source Verification

Python integrated HEAD remains `71d7cf958a41be0f40c2a350b7bcdd6027b55170`, tree
`80edbf39dcfcd504e9d1e66af7e8869d695c06f9`, plus the preexisting revision-gate
changes and this uncommitted wrapper/test delta. Existing dirty changes in
`tests/test_trusted_vsi_api.py` and `docs/trusted-vsi-python-contract.md` were
preserved; neither file was edited for this fix. Source patch fingerprint
(`git diff --binary -- src tests | sha256sum`) for this initial verification was
`30545de8d5371532fea4730143d2fbd63ac00b1bf1944251dfeb767dbd6cd52e`.

| Tested Python source | SHA-256 |
|---|---|
| `src/c2pa/c2pa.py` | `dd46aac5c2d22927c442affcda873edfe87112f91d5cf3c9822d68b5c9dcebc6` |
| `tests/test_fragmented_files.py` | `b05942c3283f05e146c0e1d536e1af862458924903def1207299409db4fba5b9` |
| Unchanged preexisting `tests/test_trusted_vsi_api.py` | `eadf6f0088b71285e7cd8c36caff47af8fdaac4cf0a710a68058a6ccf63eca89` |

The explicit loaded native library remains
`/tmp/opencode-v1.18.29/opencode/trusted-review-native-target/debug/libc2pa_c.so`,
SHA-256 `585464e737b5affd580bdf203b53920cff77075cf89e92b81c3661a9918b1950`,
checked before and after testing. Preflight confirmed the source binding path,
SDK `0.92.0-dev`, revision 3, mask 63, all six trusted-VSI probes, fragmented
capability and ladder capability. Tests used Python 3.12 and:

```sh
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
export C2PA_LIBRARY_NAME=/tmp/opencode-v1.18.29/opencode/trusted-review-native-target/debug/libc2pa_c.so
export C2PA_SOURCE_BUILD_VERSION=0.92.0-dev
export C2PA_TRUSTED_VSI_ABI_REQUIRED=1 C2PA_TRUSTED_VSI_FUNCTIONAL_REQUIRED=1
export C2PA_REQUIRE_SIGN_LADDER=1 C2PA_REQUIRE_FRAGMENTED_FILES=1
python3 -m pytest -q -p no:cacheprovider tests/test_fragmented_files.py -ra
python3 -m pytest -q -p no:cacheprovider tests/test_trusted_vsi_api.py tests/test_fragmented_files.py tests/test_sign_ladder.py tests/test_native_ownership.py tests/test_native_ownership_opaque.py tests/test_trusted_vsi_build.py -ra
python3 -m pytest -q -p no:cacheprovider --ignore=tests/test_unit_tests_threaded.py -o faulthandler_timeout=120 -ra
python3 -m pytest -q -p no:cacheprovider tests/test_unit_tests_threaded.py -o faulthandler_timeout=120 -ra
```

| Source lane | Result |
|---|---|
| Fragmented file APIs | 14 passed, 18 subtests passed |
| Focused native/ownership/build suite | 304 passed, 18 subtests passed, no skips |
| Full non-threaded source | 826 passed, 135 subtests passed, one existing installed-release-smoke module skip, 39 deprecation warnings |
| Full threaded source | 54 passed |

The final focused run (26.83s) includes an added explicit nonempty-manifest
assertion, preventing a vacuous empty-byte containment check. The full runs and
standalone fragmented run preceded that one-line test strengthening: their
fragmented test file SHA-256 was
`850aacae08cac6ebdc021e440a12c4382a749d8a02ab04e472b50bee6e2ba533`, with source
patch fingerprint `f647e32a5cc56742ad7dce598ee972fc79a8ae5644e6ee68895fd6601a68cc8c`.
The production binding and native binary were identical in all runs.

The first full non-threaded/threaded attempts exceeded the shell's 120-second
limit and were terminated, not counted as passes. Identical commands rerun with
a 600-second shell limit completed in 377.01s and 179.62s. No test expectations
or unrelated gate-test source were changed to obtain these results.

The new native-backed fragmented tests exercise the unchanged keyword interface:
two synthetic renditions derived from the committed DASH fixtures, identical
returned JUMBF bytes in both signed inits, distinct fragment selectors `(1,1)` /
`(2,2)` matching the two maps in the shared manifest, successful validation of
both renditions, rejection of changed media retaining the wrong selector,
unmodified sources, preservation of an existing destination and rejection of
an existing source-directory output at the C ABI's existing-directory preflight
(not an exercise of the SDK's filesystem identity guard), malformed init/fragment
globs, and empty matches.
They establish wrapper/native multi-init behavior, not encoding/playback of a
real ABR ladder or the signer's full regression gate. Documentation now describes
the segmented shape and distinguishes it from single-file `sign_ladder`.

This delta is source-qualified only. No wheel/sdist rebuild, installed-wheel
qualification, release-version/pin change, signer/native/B edit, commit, push,
repin, CI label or dispatch occurred; nothing was staged. Earlier wheel results
above do not qualify this new source delta. Fresh main-agent code review and
signer segmented-ABR regression remain the handoff; compatibility with the
released `0.31+stardustproof6` library was not tested here.

### Minor Review Follow-Up

The 2026-10-07 follow-up changed only four files in this Python worktree:
`tests/test_fragmented_files.py`, the `Builder.sign_fragmented` docstring in
`src/c2pa/c2pa.py`, `docs/usage.md`, and this archive. Production runtime behavior
and all preexisting revision-gate hunks remain unchanged; nothing was staged.

`cbor2` is no longer a module-level dependency of the fragmented tests. Only the
Merkle-selector test calls `pytest.importorskip("cbor2")`, lazily; missing CBOR
skips that test in optional mode but produces a clear `pytest.fail` with the
`requirements-dev.txt` install instruction when
`C2PA_REQUIRE_FRAGMENTED_FILES=1`. The fixture-only inline walker now explicitly
documents its nonzero 32-bit box-size/8-byte-header constraint; it is not a
general BMFF parser. The existing source-directory test is named/commented to
identify its earlier C ABI existing-directory rejection, not imply SDK identity
guard coverage.

The docstring and usage documentation scope init-glob and exclusive-output
guarantees to the paired glob-aware Castlabs `0.92.0-dev` native including #17.
Export presence alone does not prove those semantics in older lineages. Older
releases can contain backports (including stable Castlabs `0.80`); no blanket
pre-`0.92` rejection, fallback or new capability/version gate was added. Named
init parent directories and the `C2paError.Encoding` exception are documented.

Using the same source environment/required flags and unchanged SHA-256
`585464e737b5affd580bdf203b53920cff77075cf89e92b81c3661a9918b1950` native library
above, `pytest -q -p no:cacheprovider tests/test_fragmented_files.py -ra` passed
**14 tests / 18 subtests** in 0.73s.

A separate source-only missing-dependency simulation used an import finder to
raise `ModuleNotFoundError` for `cbor2` and `pytest`, then imported the module
with `runpy.run_path` successfully without either dependency. After unblocking
pytest (but retaining the CBOR block), with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`:

- `--collect-only tests/test_fragmented_files.py`: **14 tests collected**.
- The module excluding the Merkle-selector test, with fragmented required:
  **13 passed / 18 subtests / one deselected**.
- The Merkle-selector test with fragmented required unset: **one expected skip**.
- The same test with `C2PA_REQUIRE_FRAGMENTED_FILES=1`: **one expected failure**,
  with the missing-dev-dependency install diagnostic. The outer simulation
  asserted pytest's exit code was 1 and completed successfully; this is negative
  coverage, not a failed qualification lane.

| Final follow-up source | SHA-256 |
|---|---|
| `src/c2pa/c2pa.py` (docstring-only follow-up) | `1f9096ff4dcc0d66835d177c1b6fffc4c9f54df6b03e46b2b165d9cabea0673f` |
| `tests/test_fragmented_files.py` | `2f9615d71777e8586d2a58e04745f0029a66d8efcd3fb9aad247e39c28f61a1a` |
| `git diff --binary -- src tests` | `5dbfc02dbf128803727848a9d26b8c304d3854fb03d5e49554d3a60fdb8bd743` |

Earlier full-suite counts apply to the source snapshots identified above, not a
rerun of this follow-up. No installed-wheel qualification or rebuild is claimed;
main will rebuild/qualify the final source separately. No native/signer/B edits,
builds, commits, pushes, repins, CI changes or staging occurred.

## Final Glob-Aware Wheel Qualification

The final local qualification on 2026-10-07 supersedes the pre-glob installed
coverage above. In particular, the older `1b04b29a...` wheel does **not** qualify
the current wrapper or lazy-CBOR test follow-up. This run rebuilt both
qualification-only `0.37.13.dev0` artifacts from the latest frozen source,
including the glob-aware wrapper, final docstring, lazy `cbor2` fixture and
main's final full native workflow pin
`a6d4cdcc05638ee8dd0afce7fa5c850d7031a80c`.

Python HEAD remained `71d7cf958a41be0f40c2a350b7bcdd6027b55170` plus uncommitted
integration changes. The supplied same-production native library remained
`/tmp/opencode-v1.18.29/opencode/trusted-review-native-target/debug/libc2pa_c.so`,
SHA-256 `585464e737b5affd580bdf203b53920cff77075cf89e92b81c3661a9918b1950`.
Preflight and installed checks required SDK `0.92.0-dev`, exact contract revision
3, mask 63 and all six trusted-VSI probes true. The native production-tree/pin
handoff is provenance supplied by main; the runtime probe is not an embedded
commit attestation. No native build or target modification was performed here.

The existing build/qualifier scripts were used unchanged, offline with
`PIP_NO_INDEX=1`, a fresh output directory and a fresh system-dependency venv.
Both the source and installed dependency metadata reported `cbor2==5.9.0`.
The wheel's `c2pa/c2pa.py` bytes were hashed and compared with the frozen source
before qualification. Installed identity subsequently proved the imported
package, binding and bundled library reside under the fresh venv, with no
`PYTHONPATH`, `C2PA_LIBRARY_NAME`, `LD_LIBRARY_PATH` or `DYLD_LIBRARY_PATH`
overrides. Installed binding bytes matched that same frozen source hash.

| Final lane | Result |
|---|---|
| Installed functional qualifier (including current fragmented ABI tests) | 286 passed, 18 subtests passed |
| Explicit installed two-rendition glob/selector and destination-refusal cases | 2 passed, 2 subtests passed |
| Installed release smoke | 5 passed |
| Workflow paired/dev5 isolation test, run separately with required flags | 1 passed |
| Full non-threaded source with release smoke enabled | 831 passed, 135 subtests passed; 39 existing deprecation warnings |
| Full threaded source | 54 passed |
| `git diff --check` | Passed |

These functional lanes had **zero skips and zero deselections**. Counts overlap
and must not be summed as unique qualification. Source runs used
`PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<worktree>/src`, the explicit library
above, `C2PA_SOURCE_BUILD_VERSION=0.92.0-dev`, and all four required flags set to
`1`: `C2PA_TRUSTED_VSI_ABI_REQUIRED`, `C2PA_TRUSTED_VSI_FUNCTIONAL_REQUIRED`,
`C2PA_REQUIRE_SIGN_LADDER`, `C2PA_REQUIRE_FRAGMENTED_FILES`. Only after fresh
installed identity/qualification passed did full source runs enable
`CASTLABS_RELEASE_SMOKE_REQUIRED=1` and
`CASTLABS_RELEASE_EXPECTED_VERSION=0.37.13.dev0`, using the qualified venv's
matching metadata while explicitly loading the frozen source/native input.
The full jobs ran in separate processes under a detached, logged runner.

A separate installed-wheel missing-CBOR simulation blocked `cbor2` imports only
inside fresh child processes; it did not uninstall shared dependencies or alter
the wheel. Package-location checks proved these children used the installed
wheel with no source/library overrides. With plugin autoload disabled:

- Fragmented-module collection succeeded: **14 tests collected**, pytest exit 0.
- Optional Merkle-selector execution produced **one intentional skip**, exit 0.
- Required Merkle-selector execution produced **one expected failure**, exit 1,
  with the `C2PA_REQUIRE_FRAGMENTED_FILES=1 requires cbor2` diagnostic. The outer
  harness asserted that exit code and passed. This is negative dependency
  coverage, not a failed or skipped functional qualification lane.

Evidence/artifact root:
`/tmp/opencode-v1.18.29/opencode/python-final-glob-qualification-20261007/`.
Logs include `preflight.log`, `build.log`, `installed-focused.log`,
`installed-identity.log`, `installed-glob-abi.log`, `installed-release-smoke.log`,
`cbor-absent-collection.log`, `cbor-absent-normal.log`,
`cbor-absent-required.log`, `source-identity.log`, `workflow-isolation.log`,
`source-nonthreaded.log`, `source-threaded.log` and `runner.log`.
`status.json` reports all steps passed. `wheel-source-identity.json` and
`dist/functional-build.json` record byte/artifact identities. Before/after
snapshots in `source-before.json` and `source-after.json` are identical, excluding
only this informational archive file; staged diffs were empty. This final section
was appended afterward. No production, test, helper, workflow or pin edits were
made during this qualification.

| Final input/artifact | SHA-256 |
|---|---|
| Frozen source patch excluding this archive (`source-before.patch`) | `8d6124397272a18ad23df89444a7e4a5c0a4705a952796dd1f63b91fc0207691` |
| Source, wheel and installed `c2pa.py` | `1f9096ff4dcc0d66835d177c1b6fffc4c9f54df6b03e46b2b165d9cabea0673f` |
| `tests/test_fragmented_files.py` | `2f9615d71777e8586d2a58e04745f0029a66d8efcd3fb9aad247e39c28f61a1a` |
| `dist/c2pa_python-0.37.13.dev0-py3-none-linux_x86_64.whl` | `847666afc16fd448e0e2bbf8fc408134f3ad87dea3486c63bc45680edb80f08b` |
| `dist/c2pa_python-0.37.13.dev0.tar.gz` | `0f58c7bbdc4313c69ab7abb91ead30893308126bd52cb0d714d718f3b1066e36` |

Only this archive verification record was updated. Old artifacts/logs and
immutable dev5 inputs/evidence were preserved. Nothing was staged or committed;
no push, CI label/dispatch, publication, other-worktree edit, native build or
native-target/pin modification occurred. This is local Linux qualification, not
hosted Linux/Windows CI evidence.
