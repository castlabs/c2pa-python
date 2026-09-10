# Release notes

## Unreleased: disabled trusted-processor VSI API

- Replaces the unshipped expert EMSG scaffold with
  `TrustedVsiPrehashedSession.sign_sig_structure(sig_structure)` and
  `has_live_video_trusted_vsi_expert_sig_structure()`. No old aliases remain.
- Adds frozen `TrustedVsiSignResult`: a 64-byte fixed-format signature, uint32
  sequence number, and optional inclusive uint32 maximum not below that number.
- Mirrors the paired native signature/sequence output ABI. Split-init,
  signer-composed EMSG, status, recovery, and V1 callback-context targets remain.
- All trusted capabilities remain false. Import does not invoke the native
  trusted capability function; construction and operations reject before
  argument inspection, callbacks, native calls, or managed-resource bookkeeping.
- Adds isolated Linux/Windows paired-source API tests. This is not functional
  signing, CBOR/COSE validation, or dev5 artifact qualification. The immutable
  dev5 release, source pins, version, and publication identity are unchanged.

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
