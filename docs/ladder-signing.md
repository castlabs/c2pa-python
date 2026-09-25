# Single-File Ladder Signing

`Builder.sign_ladder(signer, sources, dests)` signs an ordered set of single-file
fragmented MP4 renditions with one shared manifest. Each input must contain its
own initialization and media fragments and one track, without an existing C2PA
manifest. A ladder contains 1 to 256 renditions. Outputs correspond to inputs by
position. Destination paths must be distinct and must not exist, and their parent
directories must exist; the native implementation validates file layouts and
overlap. Errors may leave partial newly created outputs; discard these files.

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

The native export `c2pa_builder_sign_ladder` is optional. A library without it
still imports and supports ordinary signing. Calling `sign_ladder` on that library
raises `C2paError.NotSupported`. No native release pin changes are needed for this
binding addition.

## Verification

Use a local virtual environment for dependencies. The focused mock tests run
against an otherwise supported native library:

```sh
PYTHONPATH=src C2PA_LIBRARY_NAME=/absolute/path/to/stock/libc2pa_c.so \
  .venv/bin/python -m pytest -q tests/test_sign_ladder.py
```

Run both real-native lanes explicitly. The harness copies this package and the
specified library into a temporary directory and launches a fresh Python process.
It checks the exact loaded path and SHA-256 and reports the native SDK version.
It uses the existing `C2PA_LIBRARY_NAME` loader seam, not a new loader override.
It does not replace an installed package's library.

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
