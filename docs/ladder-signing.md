# Single-File Ladder Signing

`Builder.sign_ladder(signer, sources, dests)` signs an ordered set of single-file
fragmented MP4 renditions with one shared manifest. Each input must contain its
own initialization and media fragments and one track, without an existing C2PA
manifest. A ladder contains 1 to 256 renditions. Outputs correspond to inputs by
position. Destination paths must be distinct and must not exist, and their parent
directories must exist; the native implementation validates file layouts and
overlap, and refuses to overwrite existing destinations. Errors may leave partial
outputs. Never delete sources or preexisting destinations while cleaning up a
failed operation. Delete only newly created files you positively own. Use a fresh,
exclusively owned staging directory per operation so output ownership is clear;
do not infer ownership just because a path was supplied in `dests`.

```python
with Builder(manifest_definition) as builder:
    manifest_bytes = builder.sign_ladder(
        signer,
        [Path("low.mp4"), Path("high.mp4")],
        [Path("signed-low.mp4"), Path("signed-high.mp4")],
    )
```

Pass an explicit active `Signer`, created from signing information or a callback.
This method does not fall back to a context signer. Like ordinary signing, an
attempted native call closes the builder on success or failure; the signer remains
usable. Preflight errors leave the builder usable. Paths must be UTF-8 strings
or `Path` objects and cannot contain NUL characters.

After validation, failure to admit the signing borrow (for example, an explicit
Signer closing between preflight and admission) closes the Builder too, matching
ordinary and fragmented signing. This does not change non-consuming preflight
validation failures. The call guard is a lifetime mechanism, not permission to
run concurrent native operations on either borrowed resource.

Dynamic assertions registered on the signer run once for the shared manifest.
Callback errors follow the other Builder signing paths: an exception raised by a
dynamic-assertion callback is re-raised unchanged; a claim-signer callback
propagates only interrupts such as `KeyboardInterrupt`, `SystemExit` and
`asyncio.CancelledError`, while its ordinary exceptions are reported as
`C2paError`. Error state left by a previous operation is cleared before signing.

The native export `c2pa_builder_sign_ladder` is optional. A library without it
still imports and supports ordinary signing. Calling `sign_ladder` on that library
raises `C2paError.NotSupported`. No native release pin changes are needed for this
binding addition.

## Verification

Use a local virtual environment for dependencies. The existing CI commands run
`tests/test_unit_tests.py tests/test_sign_ladder.py`. The focused ladder file
includes mock tests, typed `CFUNCTYPE` marshalling/cleanup tests, and a real-native
smoke using the committed tiny fixture and existing offline test key/certificates
(no TSA). Fixture provenance is in
`tests/fixtures/single-file-fragmented/README.md`.

```sh
PYTHONPATH=src C2PA_LIBRARY_NAME=/absolute/path/to/stock/libc2pa_c.so \
  .venv/bin/python -m pytest -q tests/test_sign_ladder.py
PYTHONPATH=src C2PA_LIBRARY_NAME=/absolute/path/to/candidate/libc2pa_c.so \
  C2PA_REQUIRE_SIGN_LADDER=1 .venv/bin/python -m pytest -q tests/test_sign_ladder.py
```

Only the native smoke skips when the loaded library lacks the optional symbol.
`C2PA_REQUIRE_SIGN_LADDER=1` makes that absence fail instead; it is a test-only
capability requirement, not a loader override or a change to the binding API.
When the symbol is present, the smoke always executes, regardless of the flag.
It checks the production export's six argument types and return type before signing.
Missing committed fixture data fails even on stock. The smoke signs two copies
of the same fixture (not different resolution encodes), checks that the returned
manifest is embedded byte-for-byte in both outputs, compares their active
manifests, requires Reader state `Valid`, and checks inputs remain unchanged.
It also checks empty-list Python preflight preserves the builder and native
signing closes it. It does not replace the broader isolated harness below.

Run both real-native lanes explicitly. The harness copies this package and the
specified library into a temporary directory and launches a fresh Python process.
It checks the exact loaded path and SHA-256 and reports the native SDK version.
It uses the existing `C2PA_LIBRARY_NAME` loader seam, not a new loader override.
It does not replace an installed package's library.

Run the harness without `-O`, `-OO`, or `PYTHONOPTIMIZE`: optimized Python is
rejected because it would disable the verification assertions.

```sh
.venv/bin/python tests/ladder_native.py --lane stock \
  --library /absolute/path/to/stock/libc2pa_c.so
.venv/bin/python tests/ladder_native.py --lane candidate \
  --library /absolute/path/to/candidate/libc2pa_c.so \
  --native-fixtures /absolute/path/to/c2pa-rs/sdk/tests/fixtures
```

The stock lane requires the export to be absent, checks the call-time typed error,
then signs and validates an ordinary JPEG with the same builder. The candidate
lane requires the export to be present: missing capability is a failure, never a
skip. It also checks ordinary signing, info and callback signers, both synthetic
`single_file_fragments*.mp4` fixtures, identical embedded manifests, validation,
media tampering, callback failure, and native rejection of source aliases,
duplicate destinations, and existing destinations without overwriting them.
Fixture hashes are included in the output; the source fixtures are never modified.
