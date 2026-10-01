# Trusted VSI Python Contract

Status: implemented and qualified against the consolidated functional native
library from `castlabs/c2pa-rs` `feat/trusted-vsi-functional` (native
`0.92.0-dev`, Rust 1.96.0, capability mask 63), following `c2pa-rs`
`docs/trusted-vsi-native-contract.md`. The paired native is pinned to
`6b506352800c8225cf5564ce99c726aaa71039f4`: `203dc08d` (ContentAuth main
`69907b5a` merged) plus CI-only fixes (rustls `0.23.45` / rustls-webpki
`0.103.15` for RUSTSEC-2026-0285, test-only lint scopes, a feature gate on a
crate-private helper, rustdoc) with no C ABI or capability change. The Python
source integrates single-file ladder signing (`Builder.sign_ladder`) and
carries the unreleased identity `0.37.13.dev0`. The `203dc08d` pairing was
qualified at source `5c64f2cc090eeb29506bc766faa69b959e4ed982` by hosted
Linux/Windows paired run `castlabs/c2pa-python` Actions 36793704783 (focused
186, real-native ladder harness, non-threaded 730, threaded 54, installed-wheel
186). Qualification of the `6b506352` pairing is recorded on
castlabs/c2pa-python#4 by run ID.

Earlier evidence: native `5c186c07` (debug `libc2pa_c.so` SHA-256
`dc79e81a084fc7b25e12423539b137f24d69693da46cb0166cb04538bd5589f9`) at source
`941c2ad5b57d23f31dbabf9fbef4776878cf630c`: local Linux focused 179 passed,
real-native ladder harness passed, non-threaded 714 passed, threaded 54 passed,
installed-wheel 179 passed; hosted Linux/Windows paired run
`castlabs/c2pa-python` Actions 36671268428 passed on both. Local qualification-only artifacts
(never published): `c2pa_python-0.37.13.dev0-py3-none-linux_x86_64.whl` SHA-256
`8731d135ce2c1db61b061e1f2c76272a55b9f7e7e2e2ea8769b10b5fd4a8707f`, sdist
`e846e5688d07bcf5959885c0c1728afde4ec89bbb7cf2b80a665956056b8b5ab`. The earlier
`0.37.9.dev0` artifacts paired with native `3569fb86` are historical evidence
only. This is unreleased API; immutable dev5 release inputs and artifacts are
unchanged. The class is `TrustedVsiSession`, and `reserve_init_uuid()` returns
`bytes` (see below).

## Availability

All `has_live_video_trusted_vsi_*()` probes return `True` only when the loaded
library exports every symbol in the contract's C ABI, reports native version
`0.92.0-dev`, and `c2pa_live_video_trusted_vsi_capabilities() == 63`. Missing
symbols, a scaffold/older/partial library, or any other mask disables every
probe. Old scaffold symbol layouts are never bound. When unavailable, the
constructor, `from_callback`, `validate_trusted_vsi_input` and
`trusted_vsi_hash_template` raise `C2paError.NotSupported` before inspecting
arguments, invoking callbacks, touching native code or managed-resource state.

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
| `export_state()` | `bytes`: versioned public JSON record (currently version 2), including pending reservations |
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
  next_sequence_number, next_event_id, exhausted, exhaustion_reason)`; optional
  fields are `None` when absent. Expert: counters `None`, `exhausted=False`.
  `exhaustion_reason` is `"sequence_max"`, `"event_id_max"` or `"legacy_sentinel"`.

Removed without aliases: `TrustedVsiPrehashedSession`, `TrustedVsiSignResult`,
`TrustedVsiInitUuidReservation`, `recover(...)`, and the private Python gate.

## Semantics For The Signer Adapter

- Expert: the processor supplies the sequence (must equal `moof/mfhd`) and owns
  ordering, replay IDs and rollover. Any sequence in `[min, max]` is accepted,
  including repeats of older sequences. Native validates canonical framing,
  signs the original bytes unchanged, never decodes the payload, keeps no counter.
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
`{"format": "c2pa.trusted-vsi.state", "version": 2, "identity", "state"}`.
Version 1 (unreleased) is rejected; there is no migration.

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
plus CI-only fixes; previously `203dc08d`, before that `5c186c07`). The status
block at the top records the qualified pairings; update that pin by full SHA
(not a branch name) for later native revisions.
