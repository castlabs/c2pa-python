# Release notes

## Version 0.37.13.dev2

Castlabs VSI prerelease (tag `castlabs-v0.37.13.dev2`, released from
`feat/trusted-vsi-functional`). It is the first published release of the
trusted-processor VSI line and true-merges the Conformance Program 0.2 /
C2PA 2.4 line (`feat/conformance-validation-v02`, published as
`0.37.12.dev3`/`0.37.12.dev4`) into it. The immutable `0.37.8.dev5` and
`0.37.12.dev*` release inputs and artifacts stay unchanged.

- Native `castlabs/c2pa-rs` `afd6fffe5a066e0b5b1a14f3f8c7ac189e7f0c95`
  (workspace `0.92.0-dev`, `Cargo.lock` SHA-256
  `f7022b3e05c2dc2080946064b386b293b29c3a60ca9daf344e1b4e3fc398c370`,
  unchanged from dev1), built with Rust `1.96.0`. It is the 1.0.8 trusted VSI
  native line (`3328b2b4`) merged with the native conformance line.
- `Reader.crjson()` emits crJSON 2.4: `validationResults.specVersion` reports
  `2.4.0`, the post-2.4 `isUpdateManifest` / `isCompressedManifest` manifest
  fields are not emitted, and `specVersion` is placed per 2.4 in
  `claim_generator_info`.
- `Reader.crjson()` is checked: the native export returns NULL with an error
  instead of `"{}"`, so exporter failures raise `C2paError`.
- `verify.validation_time` (RFC 3339) selects the evaluation instant for
  certificate, chain and OCSP decisions and the reported `validationTime`.
  Malformed values are rejected when the context is built.
- Purpose-scoped trust anchors (`trust.anchors` with `trust_kind`
  `manifest`/`tsa`/`cawg`) are always strict on this line: an anchor
  authorizes only its declared purpose. The conformance line's
  `verify.strict_trust_purposes` setting (and its non-strict fallback) does
  not exist here: the key is accepted and silently ignored, so anchors must
  carry the correct `trust_kind`.
- The installed-wheel release tests install `pytest==8.4.1` after the wheel
  on Linux and Windows; pytest is no longer a runtime dependency of the wheel
  (upstream `4d909cf`).

### 0.37.13.dev1 (not released)

Tag `castlabs-v0.37.13.dev1` (source `78771fa`, native `3328b2b4`) ran
workflow `38786913569`: the Linux build succeeded but every Linux
installed-wheel test job failed with `No module named pytest` because the
clean test venv did not install pytest; the Windows and release jobs were
cancelled. No dev1 draft or GitHub release was created and the tag remains
unchanged. Everything below ships first in dev2.

- Native `castlabs/c2pa-rs` `3328b2b440fd07d9f857cbefa3c6d565093425de`
  (workspace `0.92.0-dev`, `Cargo.lock` SHA-256
  `f7022b3e05c2dc2080946064b386b293b29c3a60ca9daf344e1b4e3fc398c370`), built
  with Rust `1.96.0`. The previous line used `9b80687f` (`0.91.0-dev`, Rust
  `1.88.0`).
- Native trusted-processor VSI line at contract revision 3 with the complete
  capability mask 63. The Python probes require the explicit revision-3 probe,
  the exact functional symbol set and mask 63, and otherwise fail closed.
- Dependency advisories fixed in the native lockfile: `event-listener` 5.4.2,
  `rustls` 0.23.46 (RUSTSEC-2026-0346 to -0349) and `quinn-proto` 0.11.18
  (RUSTSEC-2026-0338 to -0342).
- Context trust policies keep the built-in default EKU allow-list. Before the
  fix, `Store::from_context` cleared it, so `documentSigning`-only leaf
  certificates failed with `signingCredential.invalid`. Default trust anchors
  and private credentials are still not restored.
- Offset-aware fragment verification for single-file fragmented MP4:
  `has_fragment_at_offset()`, `Reader.from_fragment_at_offset()` and
  `Reader.with_fragment_at_offset()` (details below). The release smoke now
  requires `has_fragment_at_offset()`.
- `c2pa-native-version.txt` stays `c2pa-v0.91.0`. It pins the upstream
  prebuilt library that `build.yml` downloads. Source-built Castlabs libraries
  are checked against `C2PA_SOURCE_BUILD_VERSION=0.92.0-dev` instead.

### Offset-aware fragment verification

- Adds optional bindings for `c2pa_reader_with_fragment_at_offset` and
  `c2pa_reader_fragment_at_offset_supported`, `has_fragment_at_offset()`, and
  `Reader.from_fragment_at_offset()` / `Reader.with_fragment_at_offset()` to
  verify a byte-range fragment of a single-file fragmented MP4 at its absolute
  offset. Native libraries without the exports still import; the API raises
  `C2paError.NotSupported`.

### Functional trusted-processor VSI API

- Replaces the unshipped counter/result scaffold with
  `TrustedVsiSession.sign_sig_structure(sig_structure, sequence_number)
  -> bytes`. Expert mode signs supplied sequence metadata without allocating a
  sequence or keeping a media journal. `TrustedVsiSignResult` is removed.
- Renames the unshipped `TrustedVsiPrehashedSession` to `TrustedVsiSession`
  with the native contract's argument order (`context` first, `callback` after
  `validity_period_secs`); `reserve_init_uuid()` returns the UUID box bytes and
  `TrustedVsiInitUuidReservation` is removed. No aliases.
- Adds mode-pinned init/composed reserve/finalize, side-effect-free preflight,
  canonical input validation/hash templates, and explicit state export/import.
  The old unshipped `recover(init_uuid, previous_emsg)` is removed without alias.
- Pins claim/VSI/DA callbacks across context consumption, explicit close and
  state import; preserves original callback exceptions and native errors.
- Capability probes require the exact functional symbol set, native version,
  and complete capability mask. Older native libraries fail closed.
- Adds non-publishing Linux/Windows source and installed-wheel qualification.
  Functional artifacts use the source identity, `0.37.13.dev1` for this
  release (before it `0.37.13.dev0`, and historically `0.37.9.dev0` against
  native `3569fb86`). Immutable dev5 release facts, pins and artifact names
  remain unchanged. Functional native qualification is required, never an
  optional skip.
- First paired with the consolidated native `0.92.0-dev`
  (`castlabs/c2pa-rs@6b506352`, Rust 1.96.0), now `3328b2b4`. Integrates
  single-file ladder signing (`Builder.sign_ladder`). Ladder signing now propagates
  DynamicAssertion and claim-signer interrupt exceptions like the other Builder
  paths. Consume-first FFI calls (Reader/Builder `with_*`) no longer treat a
  registry rejection of another argument as proof the managed handle was
  retained, and registry tags are recognized only as the error prefix (a tag
  quoted inside another error's payload no longer establishes ownership).

## Version 0.37.12.dev4

Supersedes the published 0.37.12.dev3 (which remains unchanged). Native
`castlabs/c2pa-rs` `e1cc897d5c04d11e7773f54a659f98ec89ae224f` makes `Reader.crjson()`
conform to the published crJSON 2.4 schema: `validationResults.specVersion`
reports `2.4.0` (the validator's C2PA version) instead of `2.3.0`, and the
post-2.4 `isUpdateManifest` / `isCompressedManifest` manifest fields are no
longer emitted.

## Version 0.37.12.dev3

Supersedes 0.37.12.dev2 (run `35997070721`, cancelled before publication): the
native source is re-pinned to `6fa3e01097a87ee9265c97e00d9ec12be3052288`, whose
only change over dev2's `6ca7fb16` aligns c2patool CLI tests with contentauth
main, so native qualification passes on both platforms.

### 0.37.12.dev2 (not released)

Castlabs Conformance Program 0.2 / C2PA 2.4 candidate prerelease. Successor to
0.37.12.dev1, whose tag-triggered run `35961050991` built both platforms but
failed installed-wheel tests (pytest no longer a runtime dependency) and whose
native source failed one upstream test under `http_reqwest_blocking`; no dev1
draft or GitHub release was created.

- Native `castlabs/c2pa-rs` `6ca7fb168b10bde7a1ef8bb8e577ffbae73233c7` (dev3: `6fa3e010`): the
  live-video VSI line merged with contentauth main `6c92bc32` (C2PA 2.4
  validation), plus the single-file fMP4 Merkle and TFRA fixes.
- `verify.validation_time` (RFC 3339) selects the evaluation instant for
  certificate, chain and OCSP decisions and the reported `validationTime`.
- Purpose-scoped trust anchors (`trust.anchors` with `trust_kind`
  `manifest`/`tsa`/`cawg`) and `verify.strict_trust_purposes`.
- `Reader.crjson()` is checked: exporter failures raise instead of `{}`.
- 2.4 `specVersion` in `claim_generator_info` serializes correctly, and the
  default EKU allow-list survives context trust settings.

## Version 0.37.8.dev5

### Breaking changes

- DynamicAssertion callbacks now treat `reserve_size` as the exact serialized
  CBOR assertion size for every signing path. Dev4 and earlier accepted
  undersized callback outputs; dev5 intentionally rejects both undersized and
  oversized results with `C2paError.Assertion`. This is a breaking strictness
  change. Padding must be encoded in semantic assertion fields, such as CAWG
  `pad1` or `pad2`, rather than appended as trailing bytes.
- Exact-size DynamicAssertions work with live-video VSI initialization, media
  signing, and recovery. The earlier `assertion.bmffHash.mismatch` smoke result
  was caused by a 5-byte callback result violating its 64-byte reservation.

## Version 0.33.0

### Breaking changes

Removed the deprecated file-based free functions `read_file`,
`read_ingredient_file`, and `sign_file`, following the removal of the
underlying `c2pa_read_file`, `c2pa_read_ingredient_file`, and `c2pa_sign_file`
functions from the c2pa-rs C FFI. The deprecated `Builder.add_ingredient_from_file_path`
method was removed as well.

Migration:

- Instead of `read_file(path, data_dir)`, use `Reader(path).json()`.
- Instead of `read_ingredient_file(path, data_dir)`, use
  `Builder.add_ingredient(json, format, stream)` to add the ingredient directly.
- Instead of the `sign_file(...)` free function, use the `Builder.sign_file(source_path, dest_path, signer)` method (or `Builder.sign(...)` for stream-based signing).
- Instead of `Builder.add_ingredient_from_file_path(json, format, filepath)`, open the
  file and call `Builder.add_ingredient_from_stream(json, format, stream)`.

The `Builder.sign_file` method and `load_settings` are unaffected and remain available.

## Version 0.6.0

<!-- Get features and updates -->

See [Release tag 0.6.0](https://github.com/contentauth/c2pa-python/releases/tag/v0.6.0).

### Breaking changes

The signature of the `c2pa.sign_ps256()` method changed. Previously, the argument was a file path, but now it's the PEM certificate string.

## Version 0.5.2

New features:

- Allow EC signatures in DER format from signers and verify signature format during validation.
- Fix bug in signing audio and video files in ISO Base Media File Format (BMFF).
- Add the ability to verify PDF files (but not to sign them).
- Increase speed of `sign_file` by 2x or more, when using file paths (uses native Rust file I/O).
- Fixes for RIFF and GIF formats.

## Version 0.5.0

New features in this release:

- Rewrites the API to be stream-based using a Builder / Reader model.
- The functions now support throwing `c2pa.Error` values, caught with `try`/`except`.
- Instead of `c2pa.read_file` you now call `c2pa_api.Reader.from_file` and `reader.json`.
- Read thumbnails and other resources use `reader.resource_to_stream` or `reader.resource.to_file`.
- Instead of `c2pa.sign_file` use `c2pa_api.Builder.from_json` and `builder.sign` or `builder.sign_file`.
- Add thumbnails or other resources with `builder.add_resource` or `builder.add_resource_file`.
- Add Ingredients with `builder.add_ingredient` or `builder.add_ingredient_file`.
- You can archive a `Builder` using `builder.to_archive` and reconstruct it with `builder.from_archive`.
- Signers can be constructed with `c2pa_api.create_signer`.
- The signer now requires a signing function to keep private keys private.
- Example signing functions are provided in `c2pa_api.py`.

## Version 0.4.0

This release:

- Changes the name of the import from `c2pa-python` to `c2pa`.
- Supports pre-built platform wheels for macOS, Windows, and [manylinux](https://github.com/pypa/manylinux).

## Version 0.3.0

This release includes some breaking changes to align with future APIs:

- `C2paSignerInfo` moves the `alg` to the first parameter from the third.
- `c2pa.verify_from_file_json` is now `c2pa.read_file`.
- `c2pa.ingredient_from_file_json` is now `c2pa.read_ingredient_file`.
- `c2pa.add_manifest_to_file_json` is now `c2pa.sign_file`.
- There are many more specific error types now, and error messages always start with the name of the error, i.e., `str(err.value).startswith("ManifestNotFound")`.
- The ingredient thumbnail identifier may be a JUMBF URI reference if a valid thumb already exists in the active manifest.
- Extracted file paths for `read_file` now use a folder structure and different naming conventions.
