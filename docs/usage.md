# Using the Python library

This package works with media files in the [supported formats](https://github.com/contentauth/c2pa-rs/blob/main/docs/supported-formats.md).

For complete working examples, see the [examples folder](https://github.com/contentauth/c2pa-python/tree/main/examples) in the repository.

Reference material:
- [Class diagram](class-diagram.md)
- [API reference documentation](https://contentauth.github.io/c2pa-python/api/c2pa/index.html)

## Import

Import the objects needed from the API:

```py
from c2pa import Builder, Reader, Signer, C2paSigningAlg, C2paSignerInfo
```

If you want to use per-instance configuration with `Context` and `Settings`:

```py
from c2pa import Settings, Context, ContextBuilder, ContextProvider
```

All of `Builder`, `Reader`, `Signer`, `Context`, and `Settings` support context managers (the `with` statement) for automatic resource cleanup.

## Define manifest JSON

The Python library works with both file-based and stream-based operations.
In both cases, the manifest JSON string defines the C2PA manifest to add to an asset. For example:

```py
manifest_json = json.dumps({
    "claim_generator": "python_test/0.1",
    "assertions": [
    {
      "label": "cawg.training-mining",
      "data": {
        "entries": {
          "cawg.ai_inference": {
            "use": "notAllowed"
          },
          "cawg.ai_generative_training": {
            "use": "notAllowed"
          }
        }
      }
    }
  ]
 })
```

## Settings, Context, and ContextProvider

The `Settings` and `Context` classes provide per-instance configuration for `Reader` and `Builder` operations, replacing the global `load_settings()` function, which is now deprecated.

See [Context and settings](context-settings.md) for details.

### Settings

`Settings` controls behavior such as thumbnail generation, trust lists, and verification flags.

```py
from c2pa import Settings

settings = Settings()
settings.set("builder.thumbnail.enabled", "false")  # dot-notation path; value is a string
settings.update({"verify": {"remote_manifest_fetch": True}})  # merge additional config

settings = Settings.from_json('{"builder": {"thumbnail": {"enabled": false}}}')
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
```

For the full Settings API reference, see [Settings API](context-settings.md#settings-api).

### Context

A `Context` carries `Settings` and optionally a `Signer`, and is passed to `Reader` or `Builder` to control their behavior.

```py
from c2pa import Context, Settings

ctx = Context()  # SDK defaults
ctx = Context(settings)
ctx = Context.from_json('{"builder": {"thumbnail": {"enabled": false}}}')
ctx = Context.from_dict({"builder": {"thumbnail": {"enabled": False}}})

reader = Reader("path/to/media_file.jpg", context=ctx)
builder = Builder(manifest_json, ctx)
```

For full details on configuring `Context` and using it with `Reader` and `Builder`, see [Using Context](context-settings.md#using-context) and the [Settings reference](context-settings.md#settings-reference).

### Using ContextBuilder

`ContextBuilder` provides a fluent interface for constructing a `Context`. Use `Context.builder()` to get started; for example:

```py
from c2pa import Context, ContextBuilder, Settings, Signer

ctx = (
    Context.builder()
    .with_settings(settings)
    .with_signer(signer)
    .build()
)

ctx = Context.builder().with_settings(settings).build()
ctx = Context.builder().build()  # equivalent to Context()
```

You can call `with_settings()` multiple times; each call replaces the previous `Settings` object entirely (last one wins). To merge multiple configurations, use `Settings.update()` on a single `Settings` object before passing it to the context; for example:

```py
settings = Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}})
settings.update({"verify": {"remote_manifest_fetch": True}})

ctx = Context.builder().with_settings(settings).build()
```

### Context with a Signer

When a `Signer` is passed to `Context`, the `Signer` object is consumed and must not be reused directly. The `Context` takes ownership, enabling signing without passing an explicit signer to `Builder.sign()`:

```py
ctx = Context(settings=settings, signer=signer)
# signer is now invalid and must not be used directly again

builder = Builder(manifest_json, ctx)
with open("source.jpg", "rb") as src, open("output.jpg", "w+b") as dst:
    manifest_bytes = builder.sign(format="image/jpeg", source=src, dest=dst)
```

If both an explicit signer and a context signer are available, the explicit signer takes precedence. For more details, including remote signers, see [Configuring signers](context-settings.md#configuring-signers).

### Using ContextProvider

`ContextProvider` is an abstract base class that defines the interface `Reader` and `Builder` use to access a context. It requires two properties:

- `is_valid` (bool): Whether the provider is in a usable state.
- `execution_context`: The raw native context pointer (`C2paContext` handle).

The built-in `Context` class is the standard `ContextProvider` implementation. Custom providers must wrap a compatible native resource rather than constructing native pointers independently. `Settings` is not a `ContextProvider` and cannot be passed directly to `Reader` or `Builder`. For more details and a custom implementation example, see [ContextProvider](context-settings.md#contextprovider-abstract-base-class).

### Migrating from load_settings

The `load_settings()` function is deprecated. Replace it with `Settings` and `Context`. See [Migrating from load_settings](context-settings.md#migrating-from-load_settings) for details.

## Dynamic assertions

The Castlabs native fork can generate assertion content after the preliminary claim and its assertion hashes exist. Check the native capability before registering a callback:

```py
from c2pa import C2paError, has_dynamic_assertions

if not has_dynamic_assertions():
    raise C2paError.NotSupported("native library has no dynamic assertions")

def identity_assertion(label, reserve_size, partial_claim):
    # Each entry has url, alg, and a standard-base64 hash.
    referenced_assertions = [
        entry for entry in partial_claim
        if entry["url"].endswith("/c2pa.actions")
    ]
    return build_identity_assertion_cbor(label, referenced_assertions)

signer.add_dynamic_assertion(
    identity_assertion,
    label="cawg.identity",
    reserve_size=8192,
)
```

The callback signature is `(label: str, reserve_size: int, partial_claim: list[dict]) -> bytes`. It must return CBOR bytes no larger than `reserve_size`; oversized output is rejected rather than truncated. Multiple callbacks may use the same preferred label and run in registration order. The native layer resolves later instances with `__N` suffixes, and later callbacks see the final hashes produced by earlier callbacks.

Dynamic callbacks and their error state follow the signer into a `Context` when the signer is consumed. A Python exception raised by a callback is re-raised after the native signing operation fails. Without the Castlabs symbol, registration raises `C2paError.NotSupported`; importing the package with a standard upstream native binary remains supported.

## Live-video VSI signing

The experimental `LiveVideoVsiSession` API signs C2PA 2.4 Verifiable Segment Info directly from initialization and media segment bytes. It requires a native library built with `unstable_live_video` and an active `Context` that consumed an explicit manifest `Signer`.

```py
from c2pa import (
    Context,
    LiveVideoVsiSession,
    has_live_video_vsi,
    has_live_video_vsi_explicit_time,
)

if not has_live_video_vsi():
    raise RuntimeError("loaded native library has no live-video VSI support")
if not has_live_video_vsi_explicit_time():
    raise RuntimeError("loaded native library has no explicit-time VSI support")

context = Context(signer=manifest_signer)
clock = lambda: media_timestamp_unix_seconds
try:
    with LiveVideoVsiSession(
        manifest_json,
        context,
        seed=session_seed,  # exactly 32 bytes
        kid=b"session-key-1",
        min_sequence_number=1,
        validity_period_secs=3600,
        clock=clock,
    ) as session:
        signed_init = session.sign_init_segment(init_bytes)
        manifest_id = session.active_manifest_id
        signed_media = session.sign_media_segment(media_bytes)
        next_sequence = session.next_sequence_number
finally:
    context.close()
```

The initialization bytes must be an unsigned initialization segment. When a
`clock` is supplied, first require `has_live_video_vsi_explicit_time()`. The
clock is called exactly once for each valid media signing attempt and must
return signed 64-bit Unix seconds. That value becomes the mandatory protected
COSE `iat`, is included in the callback TBS, and drives key-validity checks;
there is no fallback to wall-clock signing if explicit-time support is absent.
The session retains the clock, native context, and any Python signer callback
while active but does not close the caller-owned `Context`. Calls on the same
session must be externally serialized.

For a non-exportable Ed25519 or ES256 session key, use the callback
constructor. The callback receives the exact final COSE Sig_structure plus
an explicit purpose and sequence; it returns a 64-byte raw signature (ES256
uses P1363 `r || s`, not DER):

```py
from c2pa import (
    C2paSigningAlg,
    LiveVideoVsiSession,
    has_live_video_vsi_callbacks,
    has_live_video_vsi_recovery,
)

if not has_live_video_vsi_callbacks():
    raise RuntimeError("loaded native library has no VSI callback support")

def sign_vsi(purpose, sequence_number, sig_structure):
    # purpose is "signer_binding" (sequence None) or "vsi" (uint32 sequence)
    return remote_keystore_sign(purpose, sequence_number, sig_structure)

with LiveVideoVsiSession.from_callback(
    manifest_json,
    context,
    callback=sign_vsi,
    algorithm=C2paSigningAlg.ES256,
    public_cose_key=public_cose_key_cbor,
    kid=b"remote-session-generation-1",
    min_sequence_number=1,
    created_at="2026-08-29T12:00:00Z",
    validity_period_secs=3600,
    clock=clock,
) as session:
    signed_init = session.sign_init_segment(init_bytes)
    signed_media = session.sign_media_segment(media_bytes)
```

Native code verifies every callback result against `public_cose_key` before
returning output or advancing counters. Python callback exceptions are
re-raised as the original exception object.

To resume after a process restart, construct the session with the same key
metadata/handle and recover from published artifacts:

```py
if not has_live_video_vsi_recovery():
    raise RuntimeError("loaded native library has no VSI recovery support")
session.recover(signed_init, last_committed_signed_media)
# `restore` is an alias of `recover`.
```

Recovery validates the init manifest, session key and signer binding, and the
last media segment's signature, BMFF hash, manifest ID, sequence, timing, and
event ID. It never invokes the session-key callback. Omitting the last media
artifact is safe only when no media from the session has ever been published;
durable callers must refuse recovery when publication state is unknown.
Recovery remains artifact-driven and does not invoke the configured clock.

## Fragmented BMFF file sets

The Castlabs native fork can sign and validate DASH/HLS-style fragmented BMFF file sets. Check the native capability before using these file-based APIs:

```py
from pathlib import Path

from c2pa import Builder, Context, Reader, has_fragmented_files

if not has_fragmented_files():
    raise RuntimeError("loaded native library has no fragmented file APIs")

output_dir = Path("signed")
with Builder(manifest_json, context=signing_context) as builder:
    manifest_bytes = builder.sign_fragmented(
        signer,
        asset_path="rendition/init.mp4",
        fragments_glob="segment-*.m4s",
        output_dir=output_dir,
    )

# Native output preserves the input parent directory below output_dir.
signed_dir = output_dir / "rendition"
with Reader.from_fragmented_files(
    signed_dir / "init.mp4",
    sorted(signed_dir.glob("segment-*.m4s")),
    context=verification_context,
) as reader:
    print(reader.json())
```

`asset_path` must be one literal existing initialization-segment file; only `fragments_glob` is a glob. A native sign attempt closes the single-use `Builder` but borrows and leaves the explicit `Signer` active. The returned manifest buffer is copied into Python-owned `bytes` and released natively.

Pass an active `Context` to `Reader.from_fragmented_files()` to use explicit verification and trust settings. Omitting `context` preserves the legacy thread-local settings behavior. The reader requires at least one explicit fragment path and retains the supplied Context and callback references until the reader closes.

## File-based operation

### Read and validate C2PA data

Use the `Reader` to read C2PA data from the specified asset file.

This examines the specified media file for C2PA data and generates a report of any data it finds. If there are validation errors, the report includes a `validation_status` field.

An asset file may contain many manifests in a manifest store. The most recent manifest is identified by the value of the `active_manifest` field in the manifests map. The manifests may contain binary resources such as thumbnails which can be retrieved with `resource_to_stream()` using the associated `identifier` field value as the URI.

> [!NOTE]
> For a comprehensive reference to the JSON manifest structure, see the [Manifest store reference](https://opensource.contentauthenticity.org/docs/manifest/manifest-ref).

Pass a `Context` to apply custom settings to the `Reader`, such as trust anchors or verification flags.

```py
try:
    settings = Settings.from_dict({
        "verify": {"verify_cert_anchors": True},
        "trust": {"trust_anchors": anchors_pem}
    })

    with Context(settings) as ctx:
        with Reader("path/to/media_file.jpg", context=ctx) as reader:
            print("Manifest store:", reader.json())

except Exception as err:
    print(err)
```

### Add a signed manifest

> [!WARNING]
> This example accesses the private key and security certificate directly from the local file system. This is fine during development, but doing so in production is insecure. Instead, use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key, as shown in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

Pass a `Context` to the `Builder` to apply custom settings during signing. The signer is still passed explicitly to `builder.sign()`.

```py
try:
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            sign_cert=cert_data,
            private_key=key_data,
            ta_url=b"http://timestamp.digicert.com"
        )

        with Context() as ctx:
            with Signer.from_info(signer_info) as signer:
                with Builder(manifest_json, ctx) as builder:
                    with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                        ingredient_json = json.dumps({"title": "Ingredient Image"})
                        builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

                    # Sign using file paths
                    builder.sign_file("path/to/source.jpg", "path/to/output.jpg", signer)

            # Verify the signed file with the same context
            with Reader("path/to/output.jpg", context=ctx) as reader:
                manifest_store = json.loads(reader.json())
                active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```

## Stream-based operations

Instead of working with files, you can read, validate, and add a signed manifest to streamed data. This example is similar to what the file-based example does.

### Read and validate manifest data

```py
try:
    settings = Settings.from_dict({"verify": {"verify_cert_anchors": True}})

    with Context(settings) as ctx:
        with open("path/to/media_file.jpg", "rb") as stream:
            with Reader("image/jpeg", stream, context=ctx) as reader:
                print("Manifest store:", reader.json())

except Exception as err:
    print(err)
```

### Add a signed manifest to a stream

> [!WARNING]
> This example accesses the private key and security certificate directly from the local file system. This is fine during development, but doing so in production is insecure. Instead, use a Key Management Service (KMS) or a hardware security module (HSM) to access the certificate and key, as shown in the [C2PA Python Example](https://github.com/contentauth/c2pa-python-example).

```py
try:
    with open("path/to/cert.pem", "rb") as cert_file, open("path/to/key.pem", "rb") as key_file:
        cert_data = cert_file.read()
        key_data = key_file.read()

        signer_info = C2paSignerInfo(
            alg=C2paSigningAlg.PS256,
            sign_cert=cert_data,
            private_key=key_data,
            ta_url=b"http://timestamp.digicert.com"
        )

        with Context() as ctx:
            with Signer.from_info(signer_info) as signer:
                with Builder(manifest_json, ctx) as builder:
                    with open("path/to/ingredient.jpg", "rb") as ingredient_file:
                        ingredient_json = json.dumps({"title": "Ingredient Image"})
                        builder.add_ingredient(ingredient_json, "image/jpeg", ingredient_file)

                    with open("path/to/source.jpg", "rb") as source, open("path/to/output.jpg", "w+b") as dest:
                        builder.sign(signer, "image/jpeg", source, dest)

            # Verify the signed file with the same context
            with open("path/to/output.jpg", "rb") as stream:
                with Reader("image/jpeg", stream, context=ctx) as reader:
                    manifest_store = json.loads(reader.json())
                    active_manifest = manifest_store["manifests"][manifest_store["active_manifest"]]
                    print("Signed manifest:", active_manifest)

except Exception as e:
    print("Failed to sign manifest store: " + str(e))
```
