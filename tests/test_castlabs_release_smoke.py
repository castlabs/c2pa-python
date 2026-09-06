"""No-skip acceptance test for wheels published by the Castlabs VSI workflow."""

from __future__ import annotations

import io
import json
import os
import tempfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pytest

if os.environ.get("CASTLABS_RELEASE_SMOKE_REQUIRED") != "1":
    pytest.skip(
        "Castlabs release smoke requires an explicitly qualified native wheel",
        allow_module_level=True,
    )

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
)

from c2pa import (
    Builder,
    C2paSignerInfo,
    C2paSigningAlg,
    Context,
    LiveVideoVsiSession,
    Reader,
    Settings,
    Signer,
    has_dynamic_assertions,
    has_fragmented_files,
    has_live_video_vsi,
    has_live_video_vsi_callbacks,
    has_live_video_vsi_explicit_time,
    has_live_video_vsi_mfhd_probe,
    has_live_video_vsi_recovery,
    moof_sequence_number,
)


FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED_VERSION = os.environ.get("CASTLABS_RELEASE_EXPECTED_VERSION", "0.37.8.dev2")
REQUIRED_CAPABILITIES = {
    "dynamic assertions": has_dynamic_assertions,
    "fragmented files": has_fragmented_files,
    "live-video VSI": has_live_video_vsi,
    "VSI callbacks": has_live_video_vsi_callbacks,
    "VSI recovery": has_live_video_vsi_recovery,
    "VSI explicit time": has_live_video_vsi_explicit_time,
    "VSI MFHD probe": has_live_video_vsi_mfhd_probe,
}


class _KnownDynamicAssertionVsiMismatch(Exception):
    pass


def _boxes(segment: bytes):
    offset = 0
    while offset < len(segment):
        if len(segment) - offset < 8:
            raise AssertionError("truncated top-level BMFF box")
        size = int.from_bytes(segment[offset : offset + 4], "big")
        box_type = segment[offset + 4 : offset + 8]
        header_size = 8
        if size == 1:
            size = int.from_bytes(segment[offset + 8 : offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = len(segment) - offset
        if size < header_size or offset + size > len(segment):
            raise AssertionError("invalid top-level BMFF box")
        yield box_type, segment[offset : offset + size]
        offset += size


def _unsigned_init() -> bytes:
    kept = [
        payload
        for box_type, payload in _boxes((FIXTURES / "dashinit.mp4").read_bytes())
        if box_type in (b"ftyp", b"moov")
    ]
    assert len(kept) == 2
    return b"".join(kept)


def _unsigned_media() -> bytes:
    return b"".join(
        payload
        for box_type, payload in _boxes((FIXTURES / "dash1.m4s").read_bytes())
        if box_type != b"uuid"
    )


def _with_sequence(segment: bytes, sequence: int) -> bytes:
    output = bytearray(segment)
    offset = output.find(b"mfhd")
    assert offset >= 0
    output[offset + 8 : offset + 12] = sequence.to_bytes(4, "big")
    return bytes(output)


def _manifest_signer() -> Signer:
    return Signer.from_info(
        C2paSignerInfo(
            alg=b"es256",
            sign_cert=(FIXTURES / "es256_certs.pem").read_bytes(),
            private_key=(FIXTURES / "es256_private.key").read_bytes(),
            ta_url=None,
        )
    )


def _dynamic_claim_signer(dynamic_calls: list[tuple[str, int, list]]) -> Signer:
    signer = _manifest_signer()

    def assertion(label, reserve_size, partial_claim):
        assert partial_claim
        dynamic_calls.append((label, reserve_size, partial_claim))
        return b"\xa1\x62id\x01"

    signer.add_dynamic_assertion(
        assertion, label="com.castlabs.release-smoke", reserve_size=64
    )
    return signer


def _manifest_definition(title: str, *, format: str) -> dict:
    return {
        "claim_generator": "castlabs_release_smoke",
        "claim_generator_info": [{"name": "castlabs_release_smoke", "version": "1"}],
        "claim_version": 2 if format == "video/mp4" else 1,
        "format": format,
        "title": title,
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": "http://c2pa.org/digitalsourcetype/empty",
                        }
                    ]
                },
            }
        ],
    }


def _cose_key(private_key, kid: bytes) -> bytes:
    numbers = private_key.public_key().public_numbers()
    return b"".join(
        (
            b"\xa6\x01\x02\x02",
            bytes((0x40 + len(kid),)),
            kid,
            b"\x03\x26\x20\x01\x21\x58\x20",
            numbers.x.to_bytes(32, "big"),
            b"\x22\x58\x20",
            numbers.y.to_bytes(32, "big"),
        )
    )


def _assert_iat(sig_structure: bytes, signing_time: int) -> None:
    assert sig_structure[:12] == b"\x84\x6aSignature1"
    initial = sig_structure[12]
    assert initial >> 5 == 2
    additional = initial & 0x1F
    if additional < 24:
        length, start = additional, 13
    elif additional == 24:
        length, start = sig_structure[13], 14
    else:
        raise AssertionError("unexpected protected-header encoding")
    assert b"\x63iat\x1a" + signing_time.to_bytes(4, "big") in (
        sig_structure[start : start + length]
    )


def test_all_castlabs_release_capabilities_are_present():
    assert version("c2pa-python") == EXPECTED_VERSION
    missing = [name for name, probe in REQUIRED_CAPABILITIES.items() if not probe()]
    assert (
        not missing
    ), f"release wheel lacks required capabilities: {', '.join(missing)}"


def test_dynamic_assertion_builder_image_signing_round_trip():
    dynamic_calls = []
    signer = _dynamic_claim_signer(dynamic_calls)
    source = (FIXTURES / "A.jpg").read_bytes()
    output = io.BytesIO()
    try:
        manifest = Builder(
            _manifest_definition(
                "Castlabs release DynamicAssertion smoke", format="image/jpeg"
            )
        ).sign(signer, "image/jpeg", io.BytesIO(source), output)
    finally:
        signer.close()
    signed = output.getvalue()
    assert manifest
    assert signed.startswith(b"\xff\xd8")
    assert len(signed) > len(source)
    assert len(dynamic_calls) == 1
    label, reserve_size, partial_claim = dynamic_calls[0]
    assert label == "com.castlabs.release-smoke"
    assert reserve_size == 64
    assert isinstance(partial_claim, list) and partial_claim
    assert any("/c2pa.actions" in entry["url"] for entry in partial_claim)
    with Reader("image/jpeg", io.BytesIO(signed)) as reader:
        report = json.loads(reader.json())
        active = report["manifests"][report["active_manifest"]]
        assert active["title"] == "Castlabs release DynamicAssertion smoke"


def test_vsi_callback_recovery_explicit_iat_and_mfhd_round_trip():
    settings = Settings()
    settings.set("verify.verify_trust", "false")
    signer = _manifest_signer()
    try:
        context = Context(settings=settings, signer=signer)
    finally:
        settings.close()

    private_key = ec.generate_private_key(ec.SECP256R1())
    kid = b"castlabs-release-vsi"
    callbacks = []

    def callback(purpose, sequence, payload):
        callbacks.append((purpose, sequence, payload))
        der = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    manifest = _manifest_definition("Castlabs release VSI smoke", format="video/mp4")
    init = _unsigned_init()
    media = _unsigned_media()
    first_sequence = moof_sequence_number(media)
    assert first_sequence > 0
    signing_time = 1_700_000_000
    created_at = (
        datetime.fromtimestamp(signing_time - 60, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    def make_session(recovery_callback):
        return LiveVideoVsiSession.from_callback(
            manifest,
            context,
            recovery_callback,
            C2paSigningAlg.ES256,
            _cose_key(private_key, kid),
            kid,
            first_sequence,
            created_at,
            3600,
        )

    try:
        with make_session(callback) as session:
            signed_init = session.sign_init_segment(init)
            signed_media = session.sign_media_segment_at(media, signing_time)
            assert session.next_sequence_number == first_sequence + 1
        assert [(purpose, sequence) for purpose, sequence, _ in callbacks] == [
            ("signer_binding", None),
            ("vsi", first_sequence),
        ]
        _assert_iat(callbacks[-1][2], signing_time)

        recovery_calls = []

        def recovery_callback(purpose, sequence, payload):
            recovery_calls.append((purpose, sequence))
            return callback(purpose, sequence, payload)

        with make_session(recovery_callback) as recovered:
            recovered.restore(signed_init, signed_media)
            assert recovery_calls == []
            next_media = _with_sequence(media, first_sequence + 1)
            assert moof_sequence_number(next_media) == first_sequence + 1
            signed_next = recovered.sign_media_segment_at(next_media, signing_time + 1)
            assert len(signed_next) > len(next_media)
            assert recovery_calls == [("vsi", first_sequence + 1)]
    finally:
        context.close()


@pytest.mark.xfail(
    raises=_KnownDynamicAssertionVsiMismatch,
    reason=(
        "pinned c2pa-rs rejects DynamicAssertion plus VSI init signing with "
        "assertion.bmffHash.mismatch"
    ),
    strict=False,
)
def test_dynamic_assertion_claim_signer_with_vsi_init_regression():
    dynamic_calls = []
    settings = Settings()
    settings.set("verify.verify_trust", "false")
    signer = _dynamic_claim_signer(dynamic_calls)
    try:
        context = Context(settings=settings, signer=signer)
    finally:
        settings.close()
    private_key = ec.generate_private_key(ec.SECP256R1())
    kid = b"castlabs-combined-vsi"

    def callback(_purpose, _sequence, payload):
        der = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    media = _unsigned_media()
    try:
        try:
            with LiveVideoVsiSession.from_callback(
                _manifest_definition(
                    "Castlabs DynamicAssertion plus VSI regression",
                    format="video/mp4",
                ),
                context,
                callback,
                C2paSigningAlg.ES256,
                _cose_key(private_key, kid),
                kid,
                moof_sequence_number(media),
                "2023-11-14T22:12:20Z",
                3600,
            ) as session:
                signed_init = session.sign_init_segment(_unsigned_init())
                assert signed_init
                assert dynamic_calls
        except Exception as error:
            if "assertion.bmffHash.mismatch" in str(error):
                raise _KnownDynamicAssertionVsiMismatch() from error
            raise
    finally:
        context.close()


def test_fragmented_file_round_trip():
    signer = Signer.from_info(
        C2paSignerInfo(
            alg=b"es256",
            sign_cert=(FIXTURES / "es256_certs.pem").read_bytes(),
            private_key=(FIXTURES / "es256_private.key").read_bytes(),
            ta_url=None,
        )
    )
    definition = {
        "claim_generator": "castlabs_release_smoke",
        "claim_generator_info": [{"name": "castlabs_release_smoke", "version": "1"}],
        "claim_version": 1,
        "format": "video/mp4",
        "title": "Castlabs release fragmented smoke",
        "assertions": [
            {
                "label": "c2pa.actions.v2",
                "data": {"actions": [{"action": "c2pa.watermarked.bound"}]},
            }
        ],
    }
    try:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "init.mp4").write_bytes(_unsigned_init())
            (input_dir / "segment-0001.m4s").write_bytes(_unsigned_media())
            builder = Builder(definition)
            manifest = builder.sign_fragmented(
                signer,
                input_dir / "init.mp4",
                "segment-*.m4s",
                root / "output",
            )
            assert manifest
            signed = root / "output" / "input"
            with Reader.from_fragmented_files(
                signed / "init.mp4", [signed / "segment-0001.m4s"]
            ) as reader:
                report = json.loads(reader.json())
                active = report["manifests"][report["active_manifest"]]
                assert active["title"] == "Castlabs release fragmented smoke"
    finally:
        signer.close()
