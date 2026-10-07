# Trusted VSI Python Contract

Status: integrated, unreleased PR4 review changes requiring native trusted-VSI
contract revision 3 (state version 3 and typed expert VSI payloads), following
`c2pa-rs`
`docs/trusted-vsi-native-contract.md`. The Python identity is `0.37.13.dev0`;
immutable dev5 release inputs and artifacts are unchanged. The paired source
workflow pins native `a6d4cdcc05638ee8dd0afce7fa5c850d7031a80c` for the
integrated revision-3 qualification batch. Select a reviewed local library with
`C2PA_LIBRARY_NAME` for integration tests. Version `0.92.0-dev` and mask 63 do not establish contract
identity; Python now requires the explicit native contract-revision probe.
Local source and installed-wheel checks passed; hosted results must be recorded
against the final source SHAs before claiming Linux/Windows qualification.
Prior results and machine-local provenance are archived in
[review verification](archive/trusted-vsi-review-verification.md).

## Availability

All `has_live_video_trusted_vsi_*()` probes return `True` only when the loaded
library exports every symbol in the contract's C ABI, reports the exact SDK
release token `c2pa-rs/0.92.0-dev`, returns
`c2pa_live_video_trusted_vsi_contract_revision() == 3`, and returns
`c2pa_live_video_trusted_vsi_capabilities() == 63`. The revision probe has the
safe stateless signature `uint32_t c2pa_live_video_trusted_vsi_contract_revision(void)`.
Only stateless probes are bound before these checks; operational trusted-VSI
ctypes signatures are bound only after every check passes. A missing revision
probe, revisions 0/1/2/4 (or any revision other than exactly 3), missing symbols,
wrong SDK version or any other mask disables all six availability probes.
There is no trial construction, status/state inspection or fallback to infer
compatibility. The SDK version is a release-line check, not a native commit or
generic SDK identity attestation. Old scaffold symbol layouts are never bound.
When unavailable, the constructor, `from_callback`, `validate_trusted_vsi_input` and
`trusted_vsi_hash_template` raise `C2paError.NotSupported` before inspecting
arguments, allocating buffers, registering/invoking callbacks, touching
operational native code or managed-resource state. Ordinary SDK signing and
legacy complete-buffer `LiveVideoVsiSession` callback bindings remain independent;
they are not feature fallbacks for trusted VSI. The observed revision is internal,
not a new public Python availability API.

## Session

```python
TrustedVsiSession.from_callback(
    context, manifest_json, algorithm, public_cose_key, kid,
    min_sequence_number, created_at, validity_period_secs, callback, *,
    mode, reservation_nonce, signing_time_unix_seconds, sequence_max=None)
```

`TrustedVsiSession(...)` takes identical arguments. Argument checks (Python
`TypeError`/`ValueError`, before any native call):

| Argument | Python type / range |
|---|---|
| `context` | active `Context` created with an explicit claim `Signer` (else `C2paError`) |
| `manifest_json` | `str` or `dict`, nonempty, no NUL |
| `algorithm` | `C2paSigningAlg.ES256`/`ED25519` or `"es256"`/`"ed25519"`/`"eddsa"` |
| `public_cose_key`, `kid` | nonempty `bytes` (public COSE_Key CBOR; private keys rejected natively) |
| `min_sequence_number` | uint32 |
| `created_at` | nonempty RFC 3339 `str` |
| `validity_period_secs` | 1 .. 2**64-1 |
| `callback` | callable `(VsiSigningContextV1, bytes) -> bytes` |
| `mode` | exactly `"expert_sig_structure"` or `"signer_composed_emsg"` |
| `reservation_nonce` | exactly 32 lowercase hex chars (public, coordinator-retained; not a key seed) |
| `signing_time_unix_seconds` | signed int64, pinned init iat |
| `sequence_max` | `None` (= UINT32_MAX) or uint32 >= `min_sequence_number` |

Keyword options serialize to the native `options_json`
(`mode`, `reservation_nonce`, `signing_time_unix_seconds`, `sequence_max`).
Construction validates configuration natively but never signs.

Methods (externally serialize calls on one session):

| Method | Result |
|---|---|
| `reserve_init_uuid(format="video/mp4")` | `bytes`: complete placeholder UUID box; repeat returns the same frozen reservation |
| `reserved_manifest_id()` | `str` |
| `finalize_init_uuid(canonical_bmff_hash: bytes)` | `bytes`: complete signed UUID, same length as reservation; identical-input replay only |
| `commit_init_uuid()` | `None`; durable coordinator activation, NOT a publication ACK |
| `sign_sig_structure(sig_structure: bytes, sequence_number: int)` | `bytes`: exactly 64 raw signature bytes (ES256 P1363 or Ed25519) |
| `reserve_media_emsg_at(sequence_number, signing_time_unix_seconds, timescale, event_duration)` | `TrustedVsiMediaEmsgReservation` |
| `finalize_media_emsg(canonical_bmff_hash: bytes)` | `bytes`: complete signed EMSG, same length as reservation |
| `export_state()` | `bytes`: versioned public JSON record (currently version 3), including pending reservations |
| `import_state(state: bytes)` | `None`; only into a NEW session with identical identity (see State records) |
| `status()` | `TrustedVsiStatus` |
| `preflight(operation, data=b"", *, sequence_number=0, iat=0, timescale=0, event_duration=0, format="video/mp4")` | `None`; no callbacks, key use, reservation or mutation |
| `close()` | idempotent; releases only this session |

Module functions: `validate_trusted_vsi_input(kind, algorithm, data: bytes) -> None`
and `trusted_vsi_hash_template(kind) -> bytes` (init/media kinds; canonical
zero-digest bmff-hash v3 template). Enums (int values accepted, bools rejected):
`TrustedVsiOperation` RESERVE_INIT=0, FINALIZE_INIT=1, COMMIT_INIT=2,
EXPERT_SIGN=3, RESERVE_MEDIA=4, FINALIZE_MEDIA=5; `TrustedVsiInputKind`
INIT_HASH=0, SIG_STRUCTURE=1, MEDIA_HASH=2.

### Value types (frozen dataclasses)

- `VsiSigningContextV1(purpose, sequence_number=None, event_id=None, exhaust_after_sign=False)`.
  `purpose` is `"signer_binding"` (no sequence/event, never exhausting) or `"vsi"`.
  Expert callbacks: `("vsi", supplied_sequence, None, False)` always, even at UINT32_MAX.
- `TrustedVsiMediaEmsgReservation(placeholder_emsg_box, signing_context,
  signing_time_unix_seconds, timescale, event_duration)` with read-only
  `sequence_number` / `event_id` properties. `signing_context` is exactly what the
  finalize callback will receive (terminal `exhaust_after_sign=True` at the limit).
- `TrustedVsiStatus(init_uuid_committed, init_uuid_pending, media_emsg_pending,
  next_sequence_number, next_event_id, exhausted, exhaustion_reason=None, blocked=False)`; optional
  fields are `None` when absent. Expert: counters `None`, `exhausted=False`.
  `exhaustion_reason` is `"sequence_max"`, `"event_id_max"` or `"legacy_sentinel"`.
  `blocked` reports an external-signing failure, independently of exhaustion.
  The C V1 layout has `blocked: bool` at offset 18; `exhaustion_reason: uint32`
  remains at offset 20 (24-byte size, 4-byte alignment).
  This native field already exists in the older workflow pin `6b506352`, including
  its `blocked: rust.blocked()` conversion; the Python bridge now exposes it.
  The integration hold is not a known missing-`blocked` ABI problem in that pin;
  the new revision gate nevertheless rejects that older library.

Removed without aliases: `TrustedVsiPrehashedSession`, `TrustedVsiSignResult`,
`TrustedVsiInitUuidReservation`, `recover(...)`, and the private Python gate.

## Semantics For The Signer Adapter

- Expert: the processor supplies the sequence (must equal `moof/mfhd`) and owns
  ordering, replay IDs and rollover. Any sequence in `[min, max]` is accepted,
  including repeats of older sequences. Native validates framing and a typed,
  untagged VSI payload map: `sequenceNumber` (uint32 matching the supplied
  sequence), `manifestId` (the pinned init ID), and `bmffHash` (the exact native
  SHA-256 media-template map with a 32-byte hash), plus optional valid
  `manifestUri` hashed-URI map. Protected headers require canonical matching
  integer `alg` and integer `iat` within the configured key window. Payload
  field order need not be canonical. Native signs the original bytes unchanged
  and keeps no expert media counter. A detached signerBinding certificate bstr
  is not an expert VSI payload. Static validation checks shape/types but cannot
  check a particular session's manifest ID or key validity window.
- Composed: reserve requires `sequence_number == next_sequence_number`
  (initially `min`); events start at 1; timing values must be positive. Reserve
  signs nothing. Finalize advances counters or exhausts without wrapping.
- The trusted processor hashes final-placement bytes with the reserved box
  installed (`trusted_vsi_hash_template` + 32-byte SHA-256 `hash`). Only
  `video/mp4` is supported. There is no C/Python hash helper; this is the
  BMFF v2+/v3 top-level rule that the native Rust reference `trusted_vsi_compute_hash`
  (`BmffHash::gen_hash_from_stream`) implements:
  SHA-256 over, for each top-level box in file order except the single excluded
  C2PA box (init: `uuid` with the C2PA UUID at offset 8; media: `emsg` with scheme
  `urn:c2pa:verifiable-segment-info` at offset 12), the box's big-endian uint64
  file offset followed by its complete bytes. Offsets are those of the FINAL
  placement. Native tests place the init UUID directly after `ftyp`, and the media
  EMSG at the front of the segment; after a leading `styp` is also valid. The
  replacement box has exactly the reserved length, so the hash is unchanged by
  finalization. See `_hash_input`/`_place` in `tests/test_trusted_vsi_api.py`.
- Verification: the signed init validates via `Reader("video/mp4", init_stream,
  context=...)`. Do NOT use `Reader.from_fragmented_files` / `with_fragment` for
  live-video VSI: that Merkle fragmented-BMFF path rejects every section 19.3 init
  manifest (`assertion.bmffHash.mismatch`, "Hash value should not be present for a
  fragmented BMFF asset"), including output from the shipped complete-buffer
  `LiveVideoVsiSession`. Media VSI EMSGs are validated by the Rust-only
  `LiveVideoValidator`; no C/Python segment validator exists. Python tests verify
  the EMSG independently: version-0 `emsg`, `urn:c2pa:verifiable-segment-info`,
  pinned timescale/duration/event ID, tagged COSE_Sign1 with protected
  `{1: alg, "iat": iat}`, unprotected `{4: kid}`, payload
  `{sequenceNumber, manifestId, bmffHash}`, where `bmffHash` equals the canonical
  hash input exactly, plus the signature over `["Signature1", protected, b"", payload]`.
- After a failure once an external signing call began, the session is blocked.
  Discard it, construct a NEW session and `import_state()` the durable
  PRE-operation record. Operation-ID/same-input retry enforcement belongs to the
  coordinator and key provider, not native V1 metadata.

## State Records

`export_state()` returns native-owned bytes; Python neither parses nor rewrites
them. Treat them as opaque, persist them atomically and authenticated, and pass
them back byte-for-byte. The native format is
`{"format": "c2pa.trusted-vsi.state", "version": 3, "identity", "state"}`.
Versions 1 and 2 (unreleased) are rejected; there is no migration.
Trusted reservation salts are deterministically derived from the public nonce
and versioned artifact/label domains, not private key material. Import and init
finalize preflight reconstruct the entire expected reservation (including static
assertions, resources and DA slots) and require byte-for-byte equality; matching
the editable identity alone is not sufficient. Signed-init imports additionally
validate full finalized-store consistency. Python treats these bytes as opaque.

`import_state()` succeeds only on a NEW session whose identity matches exactly:
mode, VSI session config/public key/kid, constructor options (including the
reservation nonce and init iat), manifest, claim-signer certificate, claim-signer
**reserve size**, and the ordered DynamicAssertion declarations (label and
reserve size of each, in registration order). Mismatches raise `C2paError`
("state record identity does not match ...") from `import_state` itself, before
any mutation and without invoking the VSI, claim-signer or DynamicAssertion
callbacks; the session remains New and usable.

Adapter consequence: the claim-signer reserve size depends on how the `Signer`
is built, not only on its certificate. For example, with the ES256 fixture
certificate `Signer.from_info` reserves 2361 bytes and `Signer.from_callback`
11836. The process that imports a record must build its Context signer the same
way (same factory, certificate, TSA setting) and register the same
DynamicAssertions in the same order as the process that exported it.

## Ownership And Errors

The caller owns its `Context`; native retains it (Arc). The session separately
pins the Python claim-signer callback, DynamicAssertion callbacks and the VSI
callback, so they survive signer consumption into the Context and caller
`Context.close()`. Returned native byte buffers are initialized to NULL, copied,
and freed exactly once with `c2pa_free`; the manifest-ID string uses
`c2pa_string_free`. Input buffers are borrowed.

Signing calls on TrustedVsiSession, complete-buffer LiveVideoVsiSession and
Builder admit a native borrow under a short per-resource lock. `close()` makes
the resource logically closed immediately and rejects new operations, but does
not cancel an admitted operation. Physical `_release` and handle free wait for
the last admitted call to return, including when close is called reentrantly
from a callback or from another thread. Builder also guards its explicit borrowed
Signer. Locks are never held across native calls or user callbacks. Callback
objects (including a copied DA list) remain pinned through `_release` and native
destruction, then become collectible. Consuming-handle ownership and Reader
stream cleanup ordering are unchanged. Builder still closes automatically after
an attempted sign, on success or failure including BaseException. If a borrowed
Signer closes after preflight and admission fails, Builder closes too; earlier
validation failures remain non-consuming. These guards do not make all resource
methods thread-safe: unguarded Reader, `with_archive()` and complete-buffer
`recover()` calls must be externally serialized with close and other operations.
Concurrent native operations also require serialization on guarded paths.

Guarded admission deliberately rejects foreign-PID inherited resources before
touching an inherited lock or making the guarded FFI call. This is a limited
behavior change from cleanup-only suppression of inherited native frees, not an
SDK-wide fork ban. Create worker-owned signers, Contexts and sessions in the
worker. Unguarded constructors accepting inherited Contexts are not uniformly
blocked; their existence does not establish safe inherited-object use. Caller
serialization obligations for unguarded operations and close remain unchanged.
See [fork safety](native-resources-management.md#fork-safety).

Errors: Python argument problems raise `TypeError`/`ValueError`. Callback results
that are not exactly 64 `bytes` raise `TypeError`/`ValueError`. Any exception
raised by the VSI callback, claim-signer callback or a DynamicAssertion callback
is re-raised with its identity intact. Native validation/state failures raise
typed `C2paError` subclasses from the native error text. Python never rewrites
CBOR, BMFF or validation results.

## Qualification Identity

`scripts/build_trusted_vsi_functional.py --library <exact-native-library> --out
<empty-dir>` first requires all probes true against that library, then builds a
NON-PUBLISHING wheel and sdist in a temporary staging copy with
`FUNCTIONAL_BUILD_VERSION` (default: the checkout's source identity
`0.37.13.dev0`; rejects `0.37.8.*`, dev5, release versions and anything older
than the source identity, including the historical `0.37.9.dev0`).
`C2PA_SOURCE_BUILD_VERSION=0.92.0-dev` identifies the native library only. The
immutable dev5 release lock and tooling are unchanged and refuse this source,
whose `pyproject.toml` version differs from the lock.

`scripts/qualify_trusted_vsi_functional.py --wheel <whl> --venv <new-dir>
--version 0.37.13.dev0` installs the wheel into an isolated venv, strips
`PYTHONPATH`/`C2PA_LIBRARY_NAME`, and runs `test_trusted_vsi_api.py`,
`test_fragmented_files.py`, `test_sign_ladder.py`,
`test_native_ownership.py` and `test_native_ownership_opaque.py` with `C2PA_TRUSTED_VSI_ABI_REQUIRED=1`,
`C2PA_REQUIRE_SIGN_LADDER=1` and `C2PA_REQUIRE_FRAGMENTED_FILES=1`; the paired
fixture asserts the imported package and native library come from that venv
with the expected version, and missing ladder or fragmented capabilities fail
rather than skip.

Paired tests require the full native library and FAIL under
`C2PA_TRUSTED_VSI_ABI_REQUIRED=1` (all Linux/Windows qualification jobs); they
skip only in ad-hoc local runs. `.github/workflows/trusted-vsi-paired.yml`
builds the native with Rust 1.96.0 from the reviewed consolidated commit
`6b506352800c8225cf5564ce99c726aaa71039f4` (ContentAuth main `69907b5a` merged
plus CI-only fixes; previously `203dc08d`, before that `5c186c07`). That older
pin emits state version 2 and lacks the required revision probe, so Python
disables trusted VSI before binding its operational ABI. Required qualification
fails with missing-symbol/revision diagnostics rather than skipping. The preserved
step2 review cdylib (`149f4b25...`) also lacks the new probe and cannot qualify
this gate. No tests or capability gates are weakened to accommodate this hold.
Final native integration/qualification and a full-SHA repin belong to a separate
authorized step, not these Python-only review changes.

## PR4 CI Gate

At head `12d265db92e8dcbf80b8255278e9a7fc5945f750`, Build run
`36810322522` completed its version/format/tooling jobs but skipped the paired
and platform test jobs. The current PR API reports author association `MEMBER`
and no labels; the source gate already accepts `COLLABORATOR` and `MEMBER`.
The retained run metadata does not establish the event-time association, so this
is not evidence that the current MEMBER condition is wrong. No author gate is
broadened here (in particular no speculative OWNER exception or fork secrets).
Do NOT apply the maintainer `safe to test` label or run paired CI expecting it to
pass until the final native revision is integrated and pinned in the separate
authorized integration step. The unchanged older native pin and the new
revision-3 gate are intentionally incompatible. Only after integration
should a maintainer review the head, apply the existing label to trigger the
`labeled` event, and confirm required jobs actually ran. This task does not post
labels, dispatch CI, or repin. A green workflow with skipped test jobs is not
qualification, and local targeted older-library compatibility checks do not lift
the integration hold.
