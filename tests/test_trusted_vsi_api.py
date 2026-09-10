from dataclasses import FrozenInstanceError, fields
import ctypes
import importlib.util
import inspect
import os
import sys
from unittest.mock import Mock

import pytest

import c2pa
import c2pa.c2pa as bindings
import c2pa.lib as library_loader


def test_trusted_vsi_scaffold_exports_and_capabilities_are_unavailable():
    assert c2pa.has_live_video_trusted_vsi_split_init() is False
    assert c2pa.has_live_video_trusted_vsi_expert_sig_structure() is False
    assert c2pa.has_live_video_trusted_vsi_composed_emsg() is False
    assert c2pa.has_live_video_trusted_vsi_recovery() is False
    assert c2pa.has_live_video_trusted_vsi_signing_context_v1() is False
    assert c2pa.has_live_video_trusted_vsi_full_uint32_exhaustion() is False
    assert bindings._TRUSTED_VSI_PYTHON_API_ENABLED is False
    assert bindings._TRUSTED_VSI_CAP_EXPERT_SIG_STRUCTURE == 2
    for module in (c2pa, bindings):
        assert "TrustedVsiSignResult" in module.__all__
        assert "has_live_video_trusted_vsi_expert_sig_structure" in module.__all__
        assert "has_live_video_trusted_vsi_expert_emsg" not in module.__all__
        assert not hasattr(module, "has_live_video_trusted_vsi_expert_emsg")
        assert all(hasattr(module, name) for name in module.__all__)
    for name in ("_TRUSTED_VSI_CAP_EXPERT_MEDIA",
                 "_TRUSTED_VSI_EXPERT_MEDIA_FUNCTIONS",
                 "_TRUSTED_VSI_EXPERT_MEDIA_AVAILABLE"):
        assert not hasattr(bindings, name)
    assert not hasattr(c2pa.TrustedVsiPrehashedSession, "sign_emsg_sig_structure")
    method = inspect.signature(c2pa.TrustedVsiPrehashedSession.sign_sig_structure)
    assert list(method.parameters) == ["self", "sig_structure"]
    assert method.return_annotation is c2pa.TrustedVsiSignResult


def test_trusted_vsi_public_values_are_immutable():
    context = c2pa.VsiSigningContextV1(
        purpose="vsi",
        sequence_number=7,
        event_id=None,
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


@pytest.mark.parametrize("sequence,maximum", [
    (0, None), (0, 0), (7, 8), (2**32 - 1, None), (2**32 - 1, 2**32 - 1),
])
def test_trusted_vsi_sign_result_is_frozen(sequence, maximum):
    result = c2pa.TrustedVsiSignResult(b"s" * 64, sequence, maximum)
    assert [field.name for field in fields(result)] == [
        "signature", "sequence_number", "sequence_max",
    ]
    assert result.signature == b"s" * 64
    assert result.sequence_number == sequence
    assert result.sequence_max == maximum
    for name in ("signature", "sequence_number", "sequence_max"):
        with pytest.raises(FrozenInstanceError):
            setattr(result, name, None)
    assert c2pa.TrustedVsiSignResult(b"s" * 64, 0).sequence_max is None


@pytest.mark.parametrize("signature,sequence,maximum,error", [
    (b"", 0, None, ValueError),
    (b"s" * 63, 0, None, ValueError),
    (b"s" * 65, 0, None, ValueError),
    (bytearray(64), 0, None, TypeError),
    ("s" * 64, 0, None, TypeError),
    (None, 0, None, TypeError),
    (b"s" * 64, -1, None, ValueError),
    (b"s" * 64, 2**32, None, ValueError),
    (b"s" * 64, True, None, TypeError),
    (b"s" * 64, None, None, TypeError),
    (b"s" * 64, 1.0, None, TypeError),
    (b"s" * 64, "1", None, TypeError),
    (b"s" * 64, 0, -1, ValueError),
    (b"s" * 64, 0, 2**32, ValueError),
    (b"s" * 64, 0, False, TypeError),
    (b"s" * 64, 0, 1.0, TypeError),
    (b"s" * 64, 0, "1", TypeError),
    (b"s" * 64, 7, 6, ValueError),
])
def test_trusted_vsi_sign_result_rejects_invalid_values(
    signature, sequence, maximum, error,
):
    with pytest.raises(error):
        c2pa.TrustedVsiSignResult(signature, sequence, maximum)


def test_trusted_vsi_import_never_invokes_native_while_gated(monkeypatch):
    functions = {}

    class NativeDeclarationsOnly:
        def __getattr__(self, name):
            if not (name.startswith("c2pa_live_video_trusted_vsi_")
                    or hasattr(bindings._lib, name)):
                raise AttributeError(name)
            return functions.setdefault(name, Mock(
                side_effect=AssertionError("native call during gated import")))

    monkeypatch.setattr(library_loader, "dynamically_load_library",
                        lambda _name: NativeDeclarationsOnly())
    spec = importlib.util.spec_from_file_location(
        "c2pa._trusted_gate_test", bindings.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module._TRUSTED_VSI_CAPABILITIES == 0
    # Even a future native library advertising every bit cannot enable Python.
    module._TRUSTED_VSI_CAPABILITIES = (1 << 6) - 1
    for name in c2pa.__all__:
        if name.startswith("has_live_video_trusted_vsi_"):
            assert getattr(module, name)() is False
    for function in functions.values():
        function.assert_not_called()


class Uninspectable:
    def __getattribute__(self, name):
        raise AssertionError("argument inspected")

    def __len__(self):
        raise AssertionError("argument length inspected")

    def __bool__(self):
        raise AssertionError("argument truth inspected")

    def __bytes__(self):
        raise AssertionError("argument converted")

    def __call__(self, *args, **kwargs):
        raise AssertionError("callback invoked")


@pytest.mark.parametrize("operation,arity", [
    ("__init__", 9), ("from_callback", 9),
    ("reserve_init_uuid", 1), ("finalize_init_uuid", 1),
    ("commit_init_uuid", 0), ("sign_sig_structure", 1),
    ("reserve_media_emsg_at", 3), ("finalize_media_emsg", 1),
    ("recover", 2), ("status", 0), ("close", 0),
    ("__enter__", 0), ("__exit__", 3), ("is_valid", 0),
    ("_wrap_native_handle", 1),
])
def test_trusted_vsi_all_operations_gate_before_side_effects(
    monkeypatch, operation, arity,
):
    forbidden = Mock(side_effect=AssertionError("resource/native side effect"))
    monkeypatch.setattr(bindings, "_lib", forbidden)
    monkeypatch.setattr(bindings.ManagedResource, "__init__", forbidden)
    monkeypatch.setattr(bindings.ManagedResource, "_cleanup_resources", forbidden)
    monkeypatch.setattr(bindings, "record_owner_pid", forbidden)
    monkeypatch.setattr(bindings.TrustedVsiPrehashedSession, "_init_attrs", forbidden)
    session = object.__new__(c2pa.TrustedVsiPrehashedSession)
    with pytest.raises(c2pa.C2paError.NotSupported, match="not enabled"):
        if operation == "is_valid":
            session.is_valid
        else:
            getattr(session, operation)(*[Uninspectable() for _ in range(arity)])
    assert vars(session) == {}
    session.__del__()
    forbidden.assert_not_called()
    assert forbidden.mock_calls == []


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


@pytest.fixture
def paired_native():
    groups = (
        bindings._TRUSTED_VSI_CAPABILITIES_FUNCTIONS,
        bindings._TRUSTED_VSI_CREATE_FUNCTIONS,
        bindings._TRUSTED_VSI_SPLIT_INIT_FUNCTIONS,
        bindings._TRUSTED_VSI_EXPERT_SIG_STRUCTURE_FUNCTIONS,
        bindings._TRUSTED_VSI_COMPOSED_MEDIA_FUNCTIONS,
        bindings._TRUSTED_VSI_RECOVERY_FUNCTIONS,
        bindings._TRUSTED_VSI_STATUS_FUNCTIONS,
    )
    missing = [name for group in groups for name in group
               if not hasattr(bindings._lib, name)]
    if missing:
        message = "paired trusted VSI ABI missing: " + ", ".join(missing)
        if os.environ.get("C2PA_TRUSTED_VSI_ABI_REQUIRED") == "1":
            pytest.fail(message)
        pytest.skip(message + " (not paired qualification)")


def test_trusted_vsi_paired_expert_prototype_and_disabled_outputs(paired_native):
    assert not hasattr(bindings._lib,
                       "c2pa_live_video_trusted_vsi_session_sign_emsg_sig_structure")
    assert bindings._lib.c2pa_live_video_trusted_vsi_capabilities() == 0
    sign = bindings._lib.c2pa_live_video_trusted_vsi_session_sign_sig_structure
    assert sign.restype is ctypes.c_int64
    assert sign.argtypes == [
        ctypes.POINTER(bindings.C2paLiveVideoTrustedVsiSession),
        ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_bool),
    ]
    sentinel = ctypes.c_ubyte(7)
    output = ctypes.pointer(sentinel)
    sequence = ctypes.c_uint32(42)
    maximum = ctypes.c_uint32(43)
    has_maximum = ctypes.c_bool(True)
    assert sign(None, None, 0, ctypes.byref(output), ctypes.byref(sequence),
                ctypes.byref(maximum), ctypes.byref(has_maximum)) == -1
    assert not output
    assert sequence.value == maximum.value == 0
    assert has_maximum.value is False


def test_trusted_vsi_paired_composed_prototype_matches_native_abi(paired_native):
    reserve = bindings._lib.c2pa_live_video_trusted_vsi_session_reserve_media_emsg
    assert reserve.argtypes[-1] == ctypes.POINTER(
        bindings.C2paLiveVideoTrustedVsiSigningContextV1
    )


def test_trusted_vsi_paired_status_prototype_matches_native_abi(paired_native):
    status = bindings._lib.c2pa_live_video_trusted_vsi_session_status_v1
    assert status.restype is ctypes.c_int
    assert status.argtypes[-1] == ctypes.POINTER(
        bindings.C2paLiveVideoTrustedVsiStatusV1
    )
