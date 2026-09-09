from dataclasses import FrozenInstanceError
import ctypes

import pytest

import c2pa
import c2pa.c2pa as bindings


def test_trusted_vsi_scaffold_exports_and_capabilities_are_unavailable():
    assert c2pa.has_live_video_trusted_vsi_split_init() is False
    assert c2pa.has_live_video_trusted_vsi_expert_emsg() is False
    assert c2pa.has_live_video_trusted_vsi_composed_emsg() is False
    assert c2pa.has_live_video_trusted_vsi_recovery() is False
    assert c2pa.has_live_video_trusted_vsi_signing_context_v1() is False
    assert c2pa.has_live_video_trusted_vsi_full_uint32_exhaustion() is False


def test_trusted_vsi_public_values_are_immutable():
    context = c2pa.VsiSigningContextV1(
        purpose="vsi",
        sequence_number=7,
        event_id=1,
        exhaust_after_sign=False,
    )
    reservation = c2pa.TrustedVsiMediaEmsgReservation(
        placeholder_emsg_box=b"emsg",
        signing_context=context,
        signing_time_unix_seconds=1_700_000_000,
        timescale=1_000,
        event_duration=2_000,
    )
    status = c2pa.TrustedVsiStatus(
        init_uuid_committed=False,
        init_uuid_pending=False,
        media_emsg_pending=False,
        next_sequence_number=7,
        next_event_id=1,
        exhausted=False,
    )
    init_reservation = c2pa.TrustedVsiInitUuidReservation(
        placeholder_uuid_box=b"uuid",
        manifest_id="urn:c2pa:manifest-1",
    )
    assert context.sequence_number == reservation.signing_context.sequence_number == 7
    assert status.next_event_id == 1
    assert init_reservation.manifest_id == "urn:c2pa:manifest-1"
    with pytest.raises(FrozenInstanceError):
        context.event_id = 2


def test_trusted_vsi_construction_fails_before_callback():
    calls = []

    def callback(context, data):
        calls.append((context, data))
        raise AssertionError("callback must not run")

    with pytest.raises(c2pa.C2paError.NotSupported, match="not enabled"):
        c2pa.TrustedVsiPrehashedSession.from_callback(
            {"assertions": []},
            object(),
            callback,
            "ES256",
            b"public-key",
            b"kid",
            1,
            "2026-01-01T00:00:00Z",
            60,
        )
    assert calls == []


def test_trusted_vsi_ctypes_declarations_match_v1_native_abi():
    context_fields = bindings.C2paLiveVideoTrustedVsiSigningContextV1._fields_
    assert [name for name, _type in context_fields] == [
        "purpose",
        "sequence_number",
        "has_sequence_number",
        "event_id",
        "has_event_id",
        "exhaust_after_sign",
    ]
    assert ctypes.sizeof(bindings.C2paLiveVideoTrustedVsiSigningContextV1) == 20
    assert ctypes.sizeof(bindings.C2paLiveVideoTrustedVsiStatusV1) == 24


def test_trusted_vsi_optional_composed_prototype_matches_native_abi():
    if not bindings._TRUSTED_VSI_COMPOSED_MEDIA_AVAILABLE:
        pytest.skip("trusted VSI composed-media symbols are not present")
    reserve = bindings._lib.c2pa_live_video_trusted_vsi_session_reserve_media_emsg
    assert reserve.argtypes[-1] == ctypes.POINTER(
        bindings.C2paLiveVideoTrustedVsiSigningContextV1
    )


def test_trusted_vsi_optional_status_prototype_matches_native_abi():
    if not bindings._TRUSTED_VSI_STATUS_AVAILABLE:
        pytest.skip("trusted VSI status symbol is not present")
    status = bindings._lib.c2pa_live_video_trusted_vsi_session_status_v1
    assert status.restype is ctypes.c_int
    assert status.argtypes[-1] == ctypes.POINTER(
        bindings.C2paLiveVideoTrustedVsiStatusV1
    )
