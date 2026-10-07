"""Trusted VSI Python bindings.

Tests named ``paired`` require the complete functional native library and FAIL
(never skip or pass) under C2PA_TRUSTED_VSI_ABI_REQUIRED=1. Legacy dev5 jobs
select only ``not paired``. Non-paired tests exercise Python gating and
marshalling against scripted native entry points; they are not functional
native qualification.
"""

import asyncio
import ctypes
from dataclasses import FrozenInstanceError
import gc
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import weakref
from unittest.mock import Mock

import cbor2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
import pytest

import c2pa
import c2pa.c2pa as bindings


FIXTURES = Path(__file__).parent / "fixtures"
IAT = 1789041600
OP = c2pa.TrustedVsiOperation
KIND = c2pa.TrustedVsiInputKind
PROBES = [getattr(c2pa, name) for name in (
    "has_live_video_trusted_vsi_split_init", "has_live_video_trusted_vsi_expert_sig_structure",
    "has_live_video_trusted_vsi_composed_emsg", "has_live_video_trusted_vsi_recovery",
    "has_live_video_trusted_vsi_signing_context_v1", "has_live_video_trusted_vsi_full_uint32_exhaustion",
)]


def _fixture_claim_signature(data):
    """Healthy ES256 claim-signer callback for the es256 fixture certificate."""
    key = serialization.load_pem_private_key(
        (FIXTURES / "es256_private.key").read_bytes(), password=None)
    return key.sign(data, ec.ECDSA(hashes.SHA256()))


def _exact_dynamic_assertion(label, reserve_size, partial_claim):
    """Canonical CBOR {"pad": h'58..'} of exactly the 64 reserved bytes."""
    assert reserve_size == 64
    return b"\xa1\x63pad\x58\x39" + b"X" * 57


# BaseException subclasses that are not Exception must also be stored by the
# ctypes wrappers and re-raised with identity; escaping into ctypes loses them.
CALLBACK_FAILURES = [
    pytest.param(lambda: RuntimeError("provider failure"), id="RuntimeError"),
    pytest.param(lambda: KeyboardInterrupt("operator interrupt"), id="KeyboardInterrupt"),
    pytest.param(lambda: SystemExit(3), id="SystemExit"),
    pytest.param(lambda: asyncio.CancelledError("worker cancelled"), id="CancelledError"),
]


def test_unshipped_counter_result_and_recovery_are_removed():
    assert not hasattr(c2pa, "TrustedVsiSignResult")
    assert not hasattr(bindings, "TrustedVsiSignResult")
    assert not hasattr(c2pa.TrustedVsiSession, "recover")
    assert not hasattr(bindings, "_TRUSTED_VSI_PYTHON_API_ENABLED")
    signature = inspect.signature(c2pa.TrustedVsiSession.sign_sig_structure)
    assert list(signature.parameters) == ["self", "sig_structure", "sequence_number"]
    assert signature.return_annotation is bytes
    for module in (c2pa, bindings):
        assert all(hasattr(module, name) for name in module.__all__)


@pytest.mark.parametrize("mask", [0, 1, 31, 62, 64, 127])
def test_partial_or_unknown_capability_mask_never_advertises_functionality(monkeypatch, mask):
    monkeypatch.setattr(bindings, "_TRUSTED_VSI_ABI_AVAILABLE", True)
    monkeypatch.setattr(bindings, "_TRUSTED_VSI_VERSION_MATCHES", True)
    monkeypatch.setattr(bindings, "_TRUSTED_VSI_CAPABILITIES", mask)
    assert not any(probe() for probe in PROBES)


@pytest.mark.parametrize("missing", ["_TRUSTED_VSI_ABI_AVAILABLE", "_TRUSTED_VSI_VERSION_MATCHES"])
def test_missing_symbols_or_wrong_native_version_fail_closed(monkeypatch, missing):
    monkeypatch.setattr(bindings, "_TRUSTED_VSI_CAPABILITIES", 63)
    monkeypatch.setattr(bindings, missing, False)
    assert not any(probe() for probe in PROBES)


def test_paired_native_version_is_exact_consolidated_release_line():
    # Changing this pin requires re-pairing qualification with a reviewed native SHA.
    assert bindings._TRUSTED_VSI_NATIVE_VERSION == "0.92.0-dev"


@pytest.mark.parametrize("native_version, expected", [
    (b"c2pa-c-ffi/0.92.0-dev c2pa-rs/0.92.0-dev", True),
    (b"c2pa-rs/0.92.0-dev", True),
    (b"c2pa-c-ffi/0.91.0-dev c2pa-rs/0.91.0-dev", False),
    (b"c2pa-c-ffi/0.92.0 c2pa-rs/0.92.0", False),
    (b"c2pa-c-ffi/0.92.0-dev c2pa-rs/0.92.0-dev.1", False),
    (b"c2pa-c-ffi/0.92.0-dev c2pa-rs/0.93.0-dev", False),
    (b"c2pa-c-ffi/0.92.0-dev", False),
    (b"xc2pa-rs/0.92.0-dev", False),
    (b"", False),
])
def test_native_version_gate_accepts_only_exact_paired_token(native_version, expected):
    assert bindings._trusted_vsi_version_matches(native_version) is expected


@pytest.mark.parametrize("factory", [c2pa.TrustedVsiSession, c2pa.TrustedVsiSession.from_callback])
def test_disabled_constructor_gates_before_arguments_callbacks_or_bookkeeping(monkeypatch, factory):
    monkeypatch.setattr(bindings, "_TRUSTED_VSI_CAPABILITIES", 0)
    forbidden = Mock(side_effect=AssertionError("side effect before capability gate"))
    monkeypatch.setattr(bindings.ManagedResource, "__init__", forbidden)
    monkeypatch.setattr(bindings, "_lib", forbidden)
    args = [object() for _ in range(9)]
    with pytest.raises(c2pa.C2paError.NotSupported, match="Functional trusted VSI"):
        factory(*args, mode=object(), reservation_nonce=object(), signing_time_unix_seconds=object())
    forbidden.assert_not_called()
    assert forbidden.mock_calls == []


def test_value_wrappers_are_frozen_and_v1_layouts_exact():
    context = c2pa.VsiSigningContextV1("vsi", 2**32 - 1)
    with pytest.raises(FrozenInstanceError):
        context.sequence_number = 0
    native = bindings.C2paLiveVideoTrustedVsiSigningContextV1
    assert ctypes.sizeof(native) == 20 and ctypes.alignment(native) == 4
    assert [getattr(native, name).offset for name, _ in native._fields_] == [0, 4, 8, 12, 16, 17]
    status = bindings.C2paLiveVideoTrustedVsiStatusV1
    assert ctypes.sizeof(status) == 24 and ctypes.alignment(status) == 4
    assert status._fields_ == [
        ("init_uuid_committed", ctypes.c_bool), ("init_uuid_pending", ctypes.c_bool),
        ("media_emsg_pending", ctypes.c_bool), ("has_next_sequence_number", ctypes.c_bool),
        ("next_sequence_number", ctypes.c_uint32), ("has_next_event_id", ctypes.c_bool),
        ("next_event_id", ctypes.c_uint32), ("exhausted", ctypes.c_bool),
        ("has_exhaustion_reason", ctypes.c_bool), ("blocked", ctypes.c_bool),
        ("exhaustion_reason", ctypes.c_uint32)]
    assert [getattr(status, name).offset for name, _ in status._fields_] == [0, 1, 2, 3, 4, 8, 12, 16, 17, 18, 20]


def test_python_mapping_matches_native_contract_signatures():
    expected = ["context", "manifest_json", "algorithm", "public_cose_key", "kid",
                "min_sequence_number", "created_at", "validity_period_secs", "callback",
                "mode", "reservation_nonce", "signing_time_unix_seconds", "sequence_max"]
    for factory in (c2pa.TrustedVsiSession.from_callback, c2pa.TrustedVsiSession.__init__):
        names = [n for n in inspect.signature(factory).parameters if n not in ("self", "cls")]
        assert names == expected
        params = inspect.signature(factory).parameters
        assert all(params[n].kind is inspect.Parameter.KEYWORD_ONLY for n in expected[9:])
    session = c2pa.TrustedVsiSession
    assert inspect.signature(session.reserve_init_uuid).return_annotation is bytes
    assert list(inspect.signature(session.reserve_media_emsg_at).parameters) == [
        "self", "sequence_number", "signing_time_unix_seconds", "timescale", "event_duration"]
    assert list(inspect.signature(session.preflight).parameters) == [
        "self", "operation", "data", "sequence_number", "iat", "timescale", "event_duration", "format"]
    for name in ("export_state", "import_state", "status", "reserved_manifest_id",
                 "finalize_init_uuid", "commit_init_uuid", "finalize_media_emsg"):
        assert callable(getattr(session, name))
    assert [m.value for m in c2pa.TrustedVsiOperation] == list(range(6))
    assert [m.value for m in c2pa.TrustedVsiInputKind] == [0, 1, 2]
    assert not hasattr(c2pa, "TrustedVsiInitUuidReservation")
    assert not hasattr(c2pa, "TrustedVsiPrehashedSession")


@pytest.mark.parametrize("function,args", [
    ("validate_trusted_vsi_input", (object(), object(), object())),
    ("trusted_vsi_hash_template", (object(),)),
])
def test_static_helpers_gate_before_arguments_or_native(monkeypatch, function, args):
    monkeypatch.setattr(bindings, "_TRUSTED_VSI_CAPABILITIES", 0)
    forbidden = Mock(side_effect=AssertionError("native touched"))
    monkeypatch.setattr(bindings, "_lib", forbidden)
    with pytest.raises(c2pa.C2paError.NotSupported):
        getattr(c2pa, function)(*args)
    forbidden.assert_not_called()


class _ScriptedNative:
    """Records calls to scripted trusted-VSI entry points installed on _lib."""

    def __init__(self, monkeypatch):
        self.calls = []
        self.freed = []
        self.buffers = []
        self.callback = None
        self.handle = ctypes.cast(ctypes.pointer(ctypes.c_int(7)),
                                  ctypes.POINTER(bindings.C2paLiveVideoTrustedVsiSession))
        self._keep = self.handle._objects
        monkeypatch.setattr(bindings, "_TRUSTED_VSI_ABI_AVAILABLE", True)
        monkeypatch.setattr(bindings, "_TRUSTED_VSI_VERSION_MATCHES", True)
        monkeypatch.setattr(bindings, "_TRUSTED_VSI_CAPABILITIES", 63)
        real_free = bindings.ManagedResource._free_native_ptr

        def free(ptr):
            # Record scripted pointers only; real native handles (e.g. the
            # caller's Context) are released by the real c2pa_free.
            address = ctypes.addressof(ptr.contents)
            scripted = {ctypes.addressof(b) for b in self.buffers}
            scripted.add(ctypes.addressof(self.handle.contents))
            if address in scripted:
                self.freed.append(address)
                return 0
            return real_free(ptr)
        monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", staticmethod(free))
        for name in bindings._TRUSTED_VSI_FUNCTIONS:
            monkeypatch.setattr(bindings._lib, name, self._unexpected(name), raising=False)

    def _unexpected(self, name):
        def call(*args):
            raise AssertionError(f"unexpected native call {name}")
        return call

    def install(self, monkeypatch, name, function):
        def recorded(*args):
            self.calls.append((name, args))
            return function(*args)
        monkeypatch.setattr(bindings._lib, "c2pa_live_video_trusted_vsi_" + name, recorded)

    def output(self, output_arg, data):
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        self.buffers.append(buffer)
        target = ctypes.cast(output_arg, ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)))
        assert not target[0], "output must be initialized to NULL"
        target[0] = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        return len(data)

    def invoke(self, purpose=1, sequence=5, has_sequence=True, event=0, has_event=False,
               exhaust=False, data=b"tbs"):
        context = bindings.C2paLiveVideoTrustedVsiSigningContextV1(
            purpose, sequence, has_sequence, event, has_event, exhaust)
        tbs = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        signature = (ctypes.c_ubyte * 64)()
        result = self.callback(None, ctypes.pointer(context), tbs, len(data), signature, 64)
        return result, bytes(signature)


@pytest.fixture
def scripted(monkeypatch):
    native = _ScriptedNative(monkeypatch)
    signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(
        alg=b"es256", sign_cert=(FIXTURES / "es256_certs.pem").read_bytes(),
        private_key=(FIXTURES / "es256_private.key").read_bytes(), ta_url=None))
    context = c2pa.Context(signer=signer)
    calls = []
    behaviour = {"result": lambda ctx, data: b"S" * 64}

    def callback(ctx, data):
        calls.append((ctx, data))
        return behaviour["result"](ctx, data)

    def create(*args):
        native.callback = args[-1]
        return native.handle
    native.install(monkeypatch, "session_create_callback_v1", create)
    session = c2pa.TrustedVsiSession(
        context, {"format": "video/mp4"}, "es256", b"\xa1\x01\x02", b"kid", 3,
        "2026-09-10T00:00:00Z", 86400, callback, mode="expert_sig_structure",
        reservation_nonce="0" * 32, signing_time_unix_seconds=IAT, sequence_max=9)
    yield native, session, context, calls, behaviour
    session.close()
    context.close()


def test_scripted_constructor_marshals_exact_order_and_options(scripted):
    native, session, context, calls, _ = scripted
    name, args = native.calls[0]
    assert name == "session_create_callback_v1" and len(args) == 13
    assert args[0] is not None and args[1] == b'{"format": "video/mp4"}'
    assert args[2] == c2pa.C2paSigningAlg.ES256
    assert bytes(args[3]) == b"\xa1\x01\x02" and args[4] == 3
    assert bytes(args[5]) == b"kid" and args[6] == 3
    assert args[7:10] == (3, b"2026-09-10T00:00:00Z", 86400)
    assert json.loads(args[10]) == {"mode": "expert_sig_structure", "reservation_nonce": "0" * 32,
                                    "signing_time_unix_seconds": IAT, "sequence_max": 9}
    assert args[11] is None and isinstance(args[12], bindings.TrustedVsiSignCallbackV1)
    assert calls == [], "construction must not sign"
    assert session.is_valid


def test_scripted_expert_sign_supplied_sequence_bytes_and_single_free(monkeypatch, scripted):
    native, session, _, calls, _ = scripted
    def sign(handle, data, length, sequence, output):
        assert ctypes.addressof(handle.contents) == ctypes.addressof(native.handle.contents)
        assert ctypes.string_at(data, length) == b"exact-sig-structure"
        result, signature = native.invoke(sequence=sequence, data=ctypes.string_at(data, length))
        assert result == 64 and signature == b"S" * 64
        return native.output(output, signature)
    native.install(monkeypatch, "session_sign_sig_structure", sign)
    for sequence in (9, 3, 2**32 - 1, 3):
        assert session.sign_sig_structure(b"exact-sig-structure", sequence) == b"S" * 64
        assert calls[-1] == (c2pa.VsiSigningContextV1("vsi", sequence), b"exact-sig-structure")
    assert [call[1][3] for call in native.calls[1:]] == [9, 3, 2**32 - 1, 3]
    assert len(native.freed) == 4
    for bad, error in ((-1, ValueError), (2**32, ValueError), (True, TypeError), ("1", TypeError)):
        with pytest.raises(error):
            session.sign_sig_structure(b"x", bad)
    with pytest.raises(TypeError):
        session.sign_sig_structure(bytearray(b"x"), 1)
    assert len(native.calls) == 5


@pytest.mark.parametrize("result,error", [
    (lambda ctx, data: b"short", ValueError),
    (lambda ctx, data: bytearray(64), TypeError),
    (None, RuntimeError),
])
def test_scripted_callback_errors_keep_identity_and_free_nothing(monkeypatch, scripted, result, error):
    native, session, _, _, behaviour = scripted
    failure = RuntimeError("provider unavailable")
    def raising(ctx, data):
        raise failure
    behaviour["result"] = result or raising
    def sign(handle, data, length, sequence, output):
        assert native.invoke(sequence=sequence)[0] == -1
        return -1
    native.install(monkeypatch, "session_sign_sig_structure", sign)
    with pytest.raises(error) as caught:
        session.sign_sig_structure(b"x", 5)
    if result is None:
        assert caught.value is failure
    assert native.freed == []


@pytest.mark.parametrize("native_context,valid", [
    ((0, 0, False, 0, False, False), True),
    ((0, 5, True, 0, False, False), False),
    ((1, 0, False, 0, False, False), False),
    ((2, 1, True, 0, False, False), False),
])
def test_scripted_callback_context_validation(scripted, native_context, valid):
    native, _, _, calls, _ = scripted
    purpose, sequence, has_sequence, event, has_event, exhaust = native_context
    result, _ = native.invoke(purpose, sequence, has_sequence, event, has_event, exhaust)
    assert (result == 64) is valid
    assert bool(calls) is valid
    if valid:
        assert calls[0][0] == c2pa.VsiSigningContextV1("signer_binding")


def test_scripted_native_error_without_callback_is_typed_and_output_absent(monkeypatch, scripted):
    native, session, _, calls, _ = scripted
    native.install(monkeypatch, "session_sign_sig_structure", lambda *args: -1)
    monkeypatch.setattr(bindings, "_read_native_error", lambda: "NotSupported: mode-pinned")
    with pytest.raises(c2pa.C2paError.NotSupported):
        session.sign_sig_structure(b"x", 5)
    assert calls == [] and native.freed == []


def test_scripted_media_reservation_status_preflight_and_state(monkeypatch, scripted):
    native, session, _, _, _ = scripted
    def reserve(handle, sequence, iat, timescale, duration, output, context):
        assert (sequence, iat, timescale, duration) == (4, IAT, 1000, 2000)
        target = ctypes.cast(context, ctypes.POINTER(bindings.C2paLiveVideoTrustedVsiSigningContextV1))
        target[0] = bindings.C2paLiveVideoTrustedVsiSigningContextV1(1, 4, True, 1, True, True)
        return native.output(output, b"emsg-box")
    native.install(monkeypatch, "session_reserve_media_emsg", reserve)
    reservation = session.reserve_media_emsg_at(4, IAT, 1000, 2000)
    assert reservation.placeholder_emsg_box == b"emsg-box"
    assert (reservation.sequence_number, reservation.event_id) == (4, 1)
    assert reservation.signing_context.exhaust_after_sign is True
    for args in ((4, IAT, 0, 1), (4, IAT, 1, 0), (2**32, IAT, 1, 1), (4, 2**63, 1, 1)):
        with pytest.raises(ValueError):
            session.reserve_media_emsg_at(*args)

    def status(handle, output):
        target = ctypes.cast(output, ctypes.POINTER(bindings.C2paLiveVideoTrustedVsiStatusV1))
        target[0] = bindings.C2paLiveVideoTrustedVsiStatusV1(
            True, False, False, True, 9, True, 2, True, True, False, 2)
        return 0
    native.install(monkeypatch, "session_status_v1", status)
    assert session.status() == c2pa.TrustedVsiStatus(True, False, False, 9, 2, True, "event_id_max")

    def preflight(handle, operation, data, length, sequence, iat, timescale, duration, format):
        assert (operation, data, length, format) == (OP.RESERVE_INIT, None, 0, b"video/mp4")
        return 0
    native.install(monkeypatch, "session_preflight", preflight)
    assert session.preflight(OP.RESERVE_INIT) is None
    with pytest.raises(ValueError):
        session.preflight(6)

    native.install(monkeypatch, "session_export_state", lambda handle, output: native.output(output, b'{"v":1}'))
    native.install(monkeypatch, "session_import_state",
                   lambda handle, data, length: 0 if ctypes.string_at(data, length) == b'{"v":1}' else -1)
    state = session.export_state()
    assert state == b'{"v":1}'
    session.import_state(state)
    freed = len(native.freed)
    assert freed == 2  # reservation + exported state; import borrows input


@pytest.mark.parametrize("kwargs,error", [
    ({"mode": "expert"}, ValueError),
    ({"mode": "composed"}, ValueError),
    ({"reservation_nonce": "A" * 32}, ValueError),
    ({"reservation_nonce": "0" * 31}, ValueError),
    ({"signing_time_unix_seconds": 1.5}, TypeError),
    ({"sequence_max": 2}, ValueError),
    ({"sequence_max": 2**32}, ValueError),
])
def test_scripted_constructor_rejects_bad_options_before_native(monkeypatch, scripted, kwargs, error):
    native, _, context, _, _ = scripted
    count = len(native.calls)
    options = dict(mode="expert_sig_structure", reservation_nonce="0" * 32,
                   signing_time_unix_seconds=IAT, sequence_max=None)
    options.update(kwargs)
    with pytest.raises(error):
        c2pa.TrustedVsiSession(context, {"format": "video/mp4"}, "es256", b"k", b"kid", 3,
                               "2026-09-10T00:00:00Z", 86400, lambda *a: b"", **options)
    assert len(native.calls) == count


def test_scripted_session_pins_callbacks_after_caller_context_close(monkeypatch, scripted):
    native, session, context, calls, _ = scripted
    context.close()
    gc.collect()
    assert session._context is context and session._trusted_vsi_callback is not None
    assert native.invoke()[0] == 64 and len(calls) == 1
    session.close()
    session.close()
    assert session._trusted_vsi_callback is None and not session.is_valid
    with pytest.raises(c2pa.C2paError):
        session.export_state()


@pytest.mark.parametrize("which", ["claim", "dynamic", "vsi"])
@pytest.mark.parametrize("make_error", CALLBACK_FAILURES)
def test_scripted_wrappers_store_base_exceptions_return_minus_one_and_reraise(
        monkeypatch, which, make_error):
    """Real ctypes wrappers + real session plumbing, scripted native calls."""
    error = make_error()

    def fail(*args):
        raise error
    certs = (FIXTURES / "es256_certs.pem").read_bytes()
    if which == "claim":
        signer = c2pa.Signer.from_callback(fail, c2pa.C2paSigningAlg.ES256, certs, None)
    else:
        signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(
            alg=b"es256", sign_cert=certs,
            private_key=(FIXTURES / "es256_private.key").read_bytes(), ta_url=None))
        if which == "dynamic":
            if not c2pa.has_dynamic_assertions():
                message = "scripted dynamic wrapper needs native registration export"
                if _qualification_required():
                    pytest.fail(message)
                pytest.skip(message)
            signer.add_dynamic_assertion(fail, label="com.example.functional", reserve_size=64)
    context = c2pa.Context(signer=signer)
    native = _ScriptedNative(monkeypatch)
    native.install(monkeypatch, "session_create_callback_v1",
                   lambda *args: setattr(native, "callback", args[-1]) or native.handle)
    session = c2pa.TrustedVsiSession(
        context, {"format": "video/mp4"}, "es256", b"k", b"kid", 1,
        "2026-09-10T00:00:00Z", 86400, fail if which == "vsi" else (lambda *a: b"S" * 64),
        mode="expert_sig_structure", reservation_nonce="0" * 32, signing_time_unix_seconds=IAT)
    context.close()
    gc.collect()
    results = []

    def finalize(handle, data, length, output):
        buffer = (ctypes.c_ubyte * 64)()
        if which == "claim":
            tbs = (ctypes.c_ubyte * 3)(1, 2, 3)
            results.append(session._signer_callback_cb(None, tbs, 3, buffer, 64))
        elif which == "dynamic":
            callback = session._dynamic_assertion_cbs[0][0]
            results.append(callback(None, b"com.example.functional", 64, b"[]", buffer, 64))
        else:
            results.append(native.invoke()[0])
        return -1
    native.install(monkeypatch, "session_finalize_init_uuid", finalize)
    try:
        with pytest.raises(type(error)) as caught:
            session.finalize_init_uuid(b"hash")
        assert caught.value is error
        assert results == [-1]
        assert native.freed == []
    finally:
        session.close()


@pytest.mark.parametrize("fails", [False, True])
def test_output_is_initialized_and_freed_once_even_on_copy_failure(monkeypatch, fails):
    buffer = (ctypes.c_ubyte * 3)(1, 2, 3)
    free = Mock()
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", free)
    def call(output):
        pointer = ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)))
        assert not pointer[0]
        pointer[0] = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        return 3
    if fails:
        monkeypatch.setattr(bindings.ctypes, "string_at", Mock(side_effect=MemoryError("copy")))
        with pytest.raises(MemoryError):
            bindings._trusted_vsi_output(call)
    else:
        assert bindings._trusted_vsi_output(call) == b"\x01\x02\x03"
    free.assert_called_once()


def _qualification_required():
    return "1" in (os.environ.get("C2PA_TRUSTED_VSI_ABI_REQUIRED"),
                   os.environ.get("C2PA_TRUSTED_VSI_FUNCTIONAL_REQUIRED"))


@pytest.fixture
def paired_native():
    """Require the complete functional native library.

    Under C2PA_TRUSTED_VSI_ABI_REQUIRED=1 (all paired qualification jobs) an
    old/scaffold/partial library is a hard FAILURE, never a skip or a pass.
    Outside qualification (e.g. an ad-hoc local run) it is reported as a skip;
    legacy dev5 jobs deselect these tests with ``-k "not paired"``.
    """
    missing = [name for name in bindings._TRUSTED_VSI_FUNCTIONS if not hasattr(bindings._lib, name)]
    problems = []
    if missing:
        problems.append("missing symbols: " + ", ".join(missing))
    expected = bindings._TRUSTED_VSI_NATIVE_VERSION
    if c2pa.sdk_version() != expected:
        problems.append(f"native version {c2pa.sdk_version()!r} != {expected!r}")
    if not missing:
        mask = int(bindings._lib.c2pa_live_video_trusted_vsi_capabilities())
        if mask != 63:
            problems.append(f"capability mask {mask} != 63")
    if not problems and not all(probe() for probe in PROBES):
        problems.append("Python capability probes are not all true")
    if problems:
        message = "Functional trusted VSI native unavailable: " + "; ".join(problems)
        if _qualification_required():
            pytest.fail(message + " (required qualification; never skipped)")
        pytest.skip(message + " (not a qualification run)")
    installed = os.environ.get("C2PA_FUNCTIONAL_INSTALLED_ROOT")
    if installed:
        root = Path(installed).resolve()
        assert Path(c2pa.__file__).resolve().is_relative_to(root)
        assert Path(bindings._lib._name).resolve().is_relative_to(root)
        assert c2pa.__version__ == os.environ["C2PA_FUNCTIONAL_EXPECTED_VERSION"]
        assert "C2PA_LIBRARY_NAME" not in os.environ and "PYTHONPATH" not in os.environ


@pytest.fixture
def sessions(paired_native):
    resources = []
    def create(mode="expert_sig_structure", algorithm="ed25519", minimum=1,
               maximum=None, callback=None, claim_callback=None, dynamic=None,
               public_cose_key=None, **overrides):
        kid = b"functional-python-session"
        if algorithm == "ed25519":
            key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
            public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            cose = {1: 1, 2: kid, 3: -8, -1: 6, -2: public}
            sign = key.sign
        else:
            key = ec.derive_private_key(7, ec.SECP256R1())
            public = key.public_key().public_numbers()
            cose = {1: 2, 2: kid, 3: -7, -1: 1, -2: public.x.to_bytes(32, "big"), -3: public.y.to_bytes(32, "big")}
            def sign(data):
                r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
                return r.to_bytes(32, "big") + s.to_bytes(32, "big")
        calls = []
        def signing(context, data):
            calls.append((context, data))
            return callback(context, data) if callback else sign(data)
        certs = (FIXTURES / "es256_certs.pem").read_bytes()
        if claim_callback is None:
            signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(
                alg=b"es256", sign_cert=certs,
                private_key=(FIXTURES / "es256_private.key").read_bytes(), ta_url=None))
        else:
            signer = c2pa.Signer.from_callback(claim_callback, c2pa.C2paSigningAlg.ES256, certs, None)
        resources.append(signer)
        if dynamic:
            signer.add_dynamic_assertion(dynamic, label="com.example.functional", reserve_size=64)
        config = json.loads((Path(__file__).parent / "trust_config_test_settings.json").read_text())
        config["builder"] = {"thumbnail": {"enabled": False}}
        context = c2pa.Context.from_dict(config, signer=signer)
        resources.append(context)
        assert not signer.is_valid
        options = dict(mode=mode, reservation_nonce="0123456789abcdef0123456789abcdef",
                       signing_time_unix_seconds=IAT, sequence_max=maximum)
        options.update(overrides)
        session = c2pa.TrustedVsiSession.from_callback(
            context,
            {"claim_version": 2, "format": "video/mp4", "assertions": [{"label": "c2pa.actions", "data": {
                "actions": [{"action": "c2pa.created", "digitalSourceType": "http://c2pa.org/digitalsourcetype/empty"}]
            }}]}, algorithm,
            public_cose_key if public_cose_key is not None else cbor2.dumps(cose, canonical=True), kid,
            minimum, "2026-09-10T00:00:00Z", 86400, signing, **options)
        resources.append(session)
        assert calls == []
        return session, calls, key, context
    yield create
    for resource in reversed(resources):
        resource.close()


def _sig_structure(algorithm="ed25519", payload=None, *, session=None, sequence=1, iat=IAT):
    protected = cbor2.dumps({1: -8 if algorithm == "ed25519" else -7, "iat": iat}, canonical=True)
    if payload is None:
        media_hash = {"alg": "sha256", "name": "jumbf manifest", "hash": bytes(32),
                      "exclusions": [{"xpath": "/emsg", "data": [
                          {"offset": 12, "value": b"urn:c2pa:verifiable-segment-info"}]}]}
        payload = cbor2.dumps({"sequenceNumber": sequence,
                              "manifestId": session.reserved_manifest_id() if session else "test-manifest",
                              "bmffHash": media_hash})
    return cbor2.dumps(["Signature1", protected, b"", payload], canonical=True)


def _boxes(data):
    offset = 0
    while offset < len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        if size == 1:
            size = int.from_bytes(data[offset + 8:offset + 16], "big")
        if size == 0:
            size = len(data) - offset
        assert size >= 8 and offset + size <= len(data)
        yield offset, data[offset + 4:offset + 8], data[offset:offset + size]
        offset += size


def _hash_input(kind, asset):
    """Trusted-processor side: hash FINAL-placement bytes (reserved box installed).

    C2PA BMFF v2+/v3 hashing inserts each included top-level box's big-endian
    uint64 offset before its bytes; fully excluded boxes contribute nothing.
    Test assets contain exactly one C2PA UUID/EMSG, which is the exclusion.
    """
    template = cbor2.loads(c2pa.trusted_vsi_hash_template(kind))
    hasher = hashlib.sha256()
    excluded = b"uuid" if kind == KIND.INIT_HASH else b"emsg"
    for offset, box_type, box in _boxes(asset):
        if box_type != excluded:
            hasher.update(offset.to_bytes(8, "big"))
            hasher.update(box)
    template["hash"] = hasher.digest()
    return cbor2.dumps(template, canonical=True)


def _place(segment, box):
    """Install a reserved box after a leading ftyp/styp, else at the front."""
    first = next(_boxes(segment))
    if first[1] in (b"ftyp", b"styp"):
        split = len(first[2])
        return segment[:split] + box + segment[split:]
    return box + segment


def _unsigned_init():
    return b"".join(box for _, kind, box in _boxes((FIXTURES / "dashinit.mp4").read_bytes())
                    if kind in (b"ftyp", b"moov"))


def _unsigned_media():
    return b"".join(box for _, kind, box in _boxes((FIXTURES / "dash1.m4s").read_bytes())
                    if kind not in (b"uuid", b"emsg"))


def _init(session):
    raw = _unsigned_init()
    reservation = session.reserve_init_uuid()
    canonical = _hash_input(KIND.INIT_HASH, _place(raw, reservation))
    final = session.finalize_init_uuid(canonical)
    assert len(final) == len(reservation)
    assert final[4:8] == b"uuid"
    # Placeholder replacement is an exact in-place substitution.
    signed = _place(raw, final)
    assert len(signed) == len(_place(raw, reservation))
    session.commit_init_uuid()
    return signed, canonical


def test_paired_ctypes_exact_functional_contract_and_error_outputs(paired_native):
    lib = bindings._lib
    session = ctypes.POINTER(bindings.C2paLiveVideoTrustedVsiSession)
    byte = ctypes.POINTER(ctypes.c_ubyte)
    output = ctypes.POINTER(byte)
    assert lib.c2pa_live_video_trusted_vsi_session_create_callback_v1.argtypes == [
        ctypes.POINTER(bindings.C2paContext), ctypes.c_char_p, ctypes.c_int, byte, ctypes.c_size_t,
        byte, ctypes.c_size_t, ctypes.c_uint64, ctypes.c_char_p, ctypes.c_uint64,
        ctypes.c_char_p, ctypes.c_void_p, bindings.TrustedVsiSignCallbackV1]
    assert lib.c2pa_live_video_trusted_vsi_session_sign_sig_structure.argtypes == [session, byte, ctypes.c_size_t, ctypes.c_uint32, output]
    assert lib.c2pa_live_video_trusted_vsi_session_reserve_media_emsg.argtypes == [
        session, ctypes.c_uint32, ctypes.c_int64, ctypes.c_uint32, ctypes.c_uint32,
        output, ctypes.POINTER(bindings.C2paLiveVideoTrustedVsiSigningContextV1)]
    assert lib.c2pa_live_video_trusted_vsi_session_preflight.argtypes == [
        session, ctypes.c_uint32, byte, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int64,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_char_p]
    sentinel = ctypes.c_ubyte(42)
    ptr = ctypes.pointer(sentinel)
    assert lib.c2pa_live_video_trusted_vsi_session_sign_sig_structure(None, None, 0, 7, ctypes.byref(ptr)) == -1
    assert not ptr
    context = bindings.C2paLiveVideoTrustedVsiSigningContextV1(1, 2, True, 3, True, True)
    ptr = ctypes.pointer(sentinel)
    assert lib.c2pa_live_video_trusted_vsi_session_reserve_media_emsg(None, 7, IAT, 1, 1, ctypes.byref(ptr), ctypes.byref(context)) == -1
    assert not ptr and bytes(context) == bytes(ctypes.sizeof(context))


@pytest.mark.parametrize("algorithm", ["ed25519", "es256"])
def test_paired_expert_exact_bytes_supplied_sequence_retry_and_no_counter(sessions, algorithm):
    session, calls, key, context = sessions(algorithm=algorithm)
    asset, _ = _init(session)
    with c2pa.Reader("video/mp4", io.BytesIO(asset), context=context) as reader:
        assert reader.get_validation_state() == "Trusted"
        assert reader.get_validation_results()["activeManifest"]["failure"] == []
    before = session.export_state()
    for sequence in (1, 37, 2**32 - 1, 1):
        original = _sig_structure(algorithm, session=session, sequence=sequence)
        c2pa.validate_trusted_vsi_input(KIND.SIG_STRUCTURE, algorithm, original)
        session.preflight(OP.EXPERT_SIGN, original, sequence_number=sequence)
        signature = session.sign_sig_structure(original, sequence)
        assert isinstance(signature, bytes) and len(signature) == 64
        if algorithm == "ed25519":
            key.public_key().verify(signature, original)
        else:
            der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
            key.public_key().verify(der, original, ec.ECDSA(hashes.SHA256()))
        assert calls[-1] == (c2pa.VsiSigningContextV1("vsi", sequence), original)
        assert session.export_state() == before
    status = session.status()
    assert status.init_uuid_committed and status.next_sequence_number is None
    assert status.next_event_id is None and not status.exhausted and status.exhaustion_reason is None
    context.close()
    gc.collect()
    assert len(session.sign_sig_structure(_sig_structure(algorithm, session=session, sequence=2), 2)) == 64


def test_paired_init_pending_export_import_preflight_and_identical_replay(sessions):
    first, calls, _, _ = sessions()
    new = first.export_state()
    first.preflight(OP.RESERVE_INIT)
    assert new == first.export_state() and calls == []
    reserved = first.reserve_init_uuid()
    assert first.reserve_init_uuid() == reserved and calls == []
    independent, independent_calls, _, _ = sessions()
    assert independent.reserve_init_uuid() == reserved and independent_calls == []
    pending = first.export_state()
    restored, restored_calls, _, context = sessions()
    restored.import_state(pending)
    assert restored_calls == [] and restored.reserve_init_uuid() == reserved
    context.close()
    gc.collect()
    canonical = c2pa.trusted_vsi_hash_template(KIND.INIT_HASH)
    restored.preflight(OP.FINALIZE_INIT, canonical)
    assert restored.export_state() == pending and restored_calls == []
    final = restored.finalize_init_uuid(canonical)
    count = len(restored_calls)
    assert len(final) == len(reserved)
    assert restored.finalize_init_uuid(canonical) == final
    assert len(restored_calls) == count
    modified = cbor2.loads(canonical)
    modified["hash"] = b"X" * 32
    with pytest.raises(c2pa.C2paError):
        restored.finalize_init_uuid(cbor2.dumps(modified, canonical=True))
    final_state = restored.export_state()
    committed, replay_calls, _, _ = sessions()
    committed.import_state(final_state)
    committed.preflight(OP.COMMIT_INIT)
    committed.commit_init_uuid()
    assert replay_calls == [] and committed.status().init_uuid_committed


def test_paired_composed_pending_import_and_uint32_exhaustion(sessions):
    session, calls, _, _ = sessions(mode="signer_composed_emsg", minimum=2**32 - 1)
    _init(session)
    before = session.export_state()
    count = len(calls)
    session.preflight(OP.RESERVE_MEDIA, sequence_number=2**32 - 1, iat=IAT, timescale=1000, event_duration=2000)
    assert session.export_state() == before and len(calls) == count
    reserved = session.reserve_media_emsg_at(2**32 - 1, IAT, 1000, 2000)
    assert len(calls) == count
    assert reserved.signing_context == c2pa.VsiSigningContextV1("vsi", 2**32 - 1, 1, True)
    pending = session.export_state()
    restored, restored_calls, _, context = sessions(mode="signer_composed_emsg", minimum=2**32 - 1)
    restored.import_state(pending)
    context.close()
    assert restored_calls == []
    assert restored.reserve_media_emsg_at(2**32 - 1, IAT, 1000, 2000) == reserved
    canonical = c2pa.trusted_vsi_hash_template(KIND.MEDIA_HASH)
    restored.preflight(OP.FINALIZE_MEDIA, canonical)
    assert restored.export_state() == pending and restored_calls == []
    final = restored.finalize_media_emsg(canonical)
    assert final[4:8] == b"emsg" and len(final) == len(reserved.placeholder_emsg_box)
    assert restored_calls[-1][0] == reserved.signing_context
    assert restored.status().exhausted and restored.status().exhaustion_reason == "sequence_max"
    assert not restored.status().blocked
    with pytest.raises(c2pa.C2paError):
        restored.reserve_media_emsg_at(0, IAT, 1000, 2000)


def _parse_vsi_emsg(box):
    """Parse an ISO/IEC 23009-1 version-0 EMSG carrying a C2PA VSI COSE_Sign1."""
    assert box[4:8] == b"emsg" and box[8] == 0
    position = 12
    fields = []
    for _ in range(2):
        end = box.index(b"\0", position)
        fields.append(box[position:end])
        position = end + 1
    timescale, delta, duration, event_id = (
        int.from_bytes(box[position + 4 * i:position + 4 * i + 4], "big") for i in range(4))
    cose = cbor2.loads(box[position + 16:])
    return fields, (timescale, delta, duration, event_id), cose


def test_paired_composed_real_fragment_native_verification(sessions):
    """Native-verified init plus independent verification of the composed EMSG.

    The Python SDK exposes no live-video segment validator (LiveVideoValidator is
    Rust-only). ``Reader.from_fragmented_files`` is NOT applicable: it implements
    the Merkle fragmented-BMFF model and rejects any init bmff hash that carries a
    top-level ``hash`` ("Hash value should not be present for a fragmented BMFF
    asset"), which C2PA 2.4 section 19.3 live-video init manifests always carry,
    including those from the shipped complete-buffer ``LiveVideoVsiSession``.
    """
    raw = _unsigned_media()
    sequence = c2pa.moof_sequence_number(raw)
    session, calls, key, context = sessions(mode="signer_composed_emsg", minimum=sequence)
    init, _ = _init(session)
    manifest_id = session.reserved_manifest_id()
    with c2pa.Reader("video/mp4", io.BytesIO(init), context=context) as reader:
        assert reader.get_validation_results()["activeManifest"]["failure"] == []
        assert reader.get_validation_state() == "Trusted"
        assert json.loads(reader.json())["active_manifest"] == manifest_id

    reserved = session.reserve_media_emsg_at(sequence, IAT, 1000, 2000)
    assert (reserved.sequence_number, reserved.event_id) == (sequence, 1)
    canonical = _hash_input(KIND.MEDIA_HASH, _place(raw, reserved.placeholder_emsg_box))
    final = session.finalize_media_emsg(canonical)
    assert len(final) == len(reserved.placeholder_emsg_box)
    signed_media = _place(raw, final)
    # The EMSG is excluded, so the final-placement hash equals the reserved one.
    assert _hash_input(KIND.MEDIA_HASH, signed_media) == canonical
    assert calls[-1][0] == reserved.signing_context

    (scheme, value), timing, cose = _parse_vsi_emsg(final)
    assert scheme == b"urn:c2pa:verifiable-segment-info"
    assert timing == (1000, 0, 2000, 1)
    assert cose.tag == 18 and len(cose.value) == 4
    protected, unprotected, payload, signature = cose.value
    assert cbor2.loads(protected) == {1: -8, "iat": IAT}
    assert unprotected == {4: b"functional-python-session"}
    info = cbor2.loads(payload)
    assert info["sequenceNumber"] == sequence
    assert info["manifestId"] == manifest_id
    assert cbor2.dumps(info["bmffHash"], canonical=True) == canonical
    sig_structure = cbor2.dumps(["Signature1", protected, b"", payload])
    assert calls[-1][1] == sig_structure
    key.public_key().verify(signature, sig_structure)
    assert value  # non-empty EMSG value per native framing


@pytest.mark.parametrize("invalid", [
    "garbage", "indefinite", "trailing", "duplicate_alg", "nonminimal_alg", "aad", "wrong_algorithm",
])
def test_paired_invalid_expert_framing_before_callback_and_no_mutation(sessions, invalid):
    session, calls, _, _ = sessions()
    _init(session)
    count, state = len(calls), session.export_state()
    data = _sig_structure(session=session)
    framing = cbor2.loads(data)
    if invalid == "garbage":
        data = b"garbage"
    elif invalid == "indefinite":
        data = b"\x9f\xff"
    elif invalid == "trailing":
        data += b"\x00"
    elif invalid == "wrong_algorithm":
        data = _sig_structure("es256", session=session)
    else:
        if invalid == "duplicate_alg":
            framing[1] = b"\xa3\x01\x27\x01\x27\x63iat" + cbor2.dumps(IAT)
        elif invalid == "nonminimal_alg":
            framing[1] = b"\xa2\x01\x38\x07\x63iat" + cbor2.dumps(IAT)
        else:
            framing[2] = b"aad"
        data = cbor2.dumps(framing)
    with pytest.raises(c2pa.C2paError):
        c2pa.validate_trusted_vsi_input(KIND.SIG_STRUCTURE, "ed25519", data)
    with pytest.raises(c2pa.C2paError):
        session.preflight(OP.EXPERT_SIGN, data, sequence_number=1)
    with pytest.raises(c2pa.C2paError):
        session.sign_sig_structure(data, 1)
    assert len(calls) == count and session.export_state() == state


def test_paired_mode_and_sequence_limits_precede_callback(sessions):
    expert, calls, _, _ = sessions(minimum=7, maximum=9)
    _init(expert)
    count = len(calls)
    for value in (6, 10):
        with pytest.raises(c2pa.C2paError):
            expert.sign_sig_structure(_sig_structure(session=expert, sequence=value), value)
    for value in (-1, 2**32, True, 1.0):
        with pytest.raises((TypeError, ValueError)):
            expert.sign_sig_structure(_sig_structure(), value)
    with pytest.raises(c2pa.C2paError):
        expert.reserve_media_emsg_at(7, IAT, 1, 1)
    assert len(calls) == count
    composed, calls, _, _ = sessions(mode="signer_composed_emsg")
    _init(composed)
    count = len(calls)
    with pytest.raises(c2pa.C2paError):
        composed.sign_sig_structure(_sig_structure(), 1)
    with pytest.raises(c2pa.C2paError):
        composed.reserve_media_emsg_at(2, IAT, 1, 1)
    assert len(calls) == count


def test_paired_callback_exception_identity_blocked_state_and_durable_retry(sessions):
    error = RuntimeError("provider lost response")
    def callback(context, data):
        if context.purpose == "vsi":
            raise error
        return ed25519.Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32).sign(data)
    session, calls, _, _ = sessions(callback=callback)
    _init(session)
    before = session.export_state()
    assert not session.status().blocked and not session.status().exhausted
    tbs = _sig_structure(session=session)
    with pytest.raises(RuntimeError) as caught:
        session.sign_sig_structure(tbs, 1)
    assert caught.value is error
    assert session.status().blocked and not session.status().exhausted
    assert session.export_state() != before
    count = len(calls)
    with pytest.raises(c2pa.C2paError):
        session.sign_sig_structure(tbs, 1)
    assert len(calls) == count
    restored, _, _, _ = sessions()
    restored.import_state(before)
    assert not restored.status().blocked
    assert len(restored.sign_sig_structure(tbs, 1)) == 64




@pytest.mark.parametrize("scenario", ["direct", "context_closed", "imported"])
@pytest.mark.parametrize("which", ["claim", "dynamic"])
@pytest.mark.parametrize("make_error", CALLBACK_FAILURES)
def test_paired_claim_and_da_errors_keep_identity_and_block(sessions, which, scenario, make_error):
    error = make_error()
    failures = []

    def fail(*args):
        failures.append(args)
        raise error
    failing = {"claim_callback": fail} if which == "claim" else {"dynamic": fail}
    if scenario == "imported":
        # Pending state from a healthy session with the same claim certificate and
        # DynamicAssertion declaration (label/reserve size), finalized by a NEW
        # session whose Context signer/DA fails and whose Context is closed.
        # Declarations must be identical (native v3 state pins the claim
        # signer's reserve size and ordered DA label/reserve size), so the
        # healthy claim signer is also a from_callback signer with the same
        # certificate; only its signing behavior differs.
        healthy = ({"claim_callback": _fixture_claim_signature} if which == "claim"
                   else {"dynamic": _exact_dynamic_assertion})
        original, _, _, _ = sessions(**healthy)
        original.reserve_init_uuid()
        pending = original.export_state()
        session, calls, _, context = sessions(**failing)
        session.import_state(pending)
    else:
        session, calls, _, context = sessions(**failing)
        session.reserve_init_uuid()
    if scenario != "direct":
        context.close()
        gc.collect()
    canonical = c2pa.trusted_vsi_hash_template(KIND.INIT_HASH)
    assert not session.status().blocked
    with pytest.raises(type(error)) as caught:
        session.finalize_init_uuid(canonical)
    assert caught.value is error
    assert session.status().blocked and not session.status().exhausted
    assert len(failures) == 1
    # The external signing attempt blocks the local session: no retry, no
    # further callback, and init is never committed.
    vsi_calls = len(calls)
    with pytest.raises(c2pa.C2paError):
        session.finalize_init_uuid(canonical)
    with pytest.raises(c2pa.C2paError):
        session.commit_init_uuid()
    assert len(failures) == 1 and len(calls) == vsi_calls
    assert not session.status().init_uuid_committed


@pytest.mark.parametrize("reserving,importing", [
    pytest.param({}, {"claim_callback": "callback"}, id="claim-reserve-size-2361-vs-11836"),
    pytest.param({"claim_callback": "callback"}, {}, id="claim-reserve-size-11836-vs-2361"),
    pytest.param({}, {"dynamic": [("com.example.a", 64)]}, id="da-added"),
    pytest.param({"dynamic": [("com.example.a", 64)]}, {}, id="da-removed"),
    pytest.param({"dynamic": [("com.example.a", 64)]}, {"dynamic": [("com.example.b", 64)]}, id="da-label"),
    pytest.param({"dynamic": [("com.example.a", 64)]}, {"dynamic": [("com.example.a", 96)]}, id="da-reserve-size"),
    pytest.param({"dynamic": [("com.example.a", 64), ("com.example.b", 64)]},
                 {"dynamic": [("com.example.b", 64), ("com.example.a", 64)]}, id="da-order"),
])
def test_paired_import_rejects_mismatched_claim_and_da_declarations(paired_native, reserving, importing):
    """v3 identity pins claim reserve size and ordered DA declarations.

    A mismatch must be rejected by import_state itself, before mutation and
    without invoking the VSI session key, claim signer, or any DA callback.
    """
    certs = (FIXTURES / "es256_certs.pem").read_bytes()
    touched = []
    resources = []

    def build(declarations, record):
        def claim(data):
            touched.append(("claim", record))
            return _fixture_claim_signature(data)
        if declarations.get("claim_callback"):
            signer = c2pa.Signer.from_callback(claim, c2pa.C2paSigningAlg.ES256, certs, None)
        else:
            signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(
                alg=b"es256", sign_cert=certs,
                private_key=(FIXTURES / "es256_private.key").read_bytes(), ta_url=None))
        for label, size in declarations.get("dynamic", ()):
            def dynamic(*args, label=label):
                touched.append(("dynamic", record, label))
                return _exact_dynamic_assertion(*args)
            signer.add_dynamic_assertion(dynamic, label=label, reserve_size=size)
        context = c2pa.Context(signer=signer)
        resources.append(context)
        key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        kid = b"functional-python-session"

        def vsi(ctx, data):
            touched.append(("vsi", record))
            return key.sign(data)
        session = c2pa.TrustedVsiSession(
            context, {"claim_version": 2, "format": "video/mp4"}, "ed25519",
            cbor2.dumps({1: 1, 2: kid, 3: -8, -1: 6, -2: public}, canonical=True), kid,
            1, "2026-09-10T00:00:00Z", 86400, vsi, mode="expert_sig_structure",
            reservation_nonce="0123456789abcdef0123456789abcdef", signing_time_unix_seconds=IAT)
        resources.append(session)
        return session

    try:
        reserving_session = build(reserving, "reserving")
        reserving_session.reserve_init_uuid()
        record = reserving_session.export_state()
        state = json.loads(record)
        assert (state["format"], state["version"]) == ("c2pa.trusted-vsi.state", 3)
        assert [(d["label"], d["reserve_size"]) for d in state["identity"]["dynamic_assertions"]] == \
            list(reserving.get("dynamic", ()))
        importing_session = build(importing, "importing")
        fresh = importing_session.export_state()
        with pytest.raises(c2pa.C2paError, match="identity does not match"):
            importing_session.import_state(record)
        assert importing_session.export_state() == fresh
        status = importing_session.status()
        assert not status.init_uuid_pending and not status.init_uuid_committed
        assert touched == []
        # Still a usable New session: its own reservation works afterwards.
        importing_session.reserve_init_uuid()
        assert touched == []
    finally:
        for resource in reversed(resources):
            resource.close()


def test_paired_import_rejects_mismatched_mode_options_and_corruption(sessions):
    session, _, _, _ = sessions()
    session.reserve_init_uuid()
    state = session.export_state()
    for options in ({"mode": "signer_composed_emsg"}, {"reservation_nonce": "a" * 32}):
        other, calls, _, _ = sessions(**options)
        before = other.export_state()
        with pytest.raises(c2pa.C2paError):
            other.import_state(state)
        assert other.export_state() == before and calls == []
    other, calls, _, _ = sessions()
    with pytest.raises(c2pa.C2paError):
        other.import_state(state[:-1])
    assert calls == []
    session.close()
    session.close()
    assert not session.is_valid
    with pytest.raises(c2pa.C2paError):
        session.export_state()


def test_paired_invalid_public_key_and_algorithm_fail_before_callback(sessions):
    callback = Mock(side_effect=AssertionError("key used before validation"))
    for key in (b"invalid", cbor2.dumps({1: 1, 2: b"functional-python-session", 3: -8,
                                       -1: 6, -2: b"X" * 32, -4: b"secret" * 6}, canonical=True)):
        with pytest.raises(c2pa.C2paError):
            sessions(public_cose_key=key, callback=callback)
    with pytest.raises(ValueError):
        sessions(algorithm="ps256", callback=callback)
    callback.assert_not_called()


@pytest.mark.parametrize("signature,error", [(b"bad", ValueError), (bytearray(64), TypeError), (bytes(64), c2pa.C2paError)])
def test_paired_invalid_signatures_preserve_errors_and_block_session(sessions, signature, error):
    session, calls, _, _ = sessions(callback=lambda *_: signature)
    session.reserve_init_uuid()
    with pytest.raises(error):
        session.finalize_init_uuid(c2pa.trusted_vsi_hash_template(KIND.INIT_HASH))
    assert len(calls) == 1
    with pytest.raises(c2pa.C2paError):
        session.finalize_init_uuid(c2pa.trusted_vsi_hash_template(KIND.INIT_HASH))
    assert len(calls) == 1


def test_paired_claim_and_dynamic_callbacks_survive_pending_import_and_close(sessions):
    claim_calls, da_calls = [], []
    key = serialization.load_pem_private_key((FIXTURES / "es256_private.key").read_bytes(), password=None)
    def claim(data):
        claim_calls.append(data)
        return key.sign(data, ec.ECDSA(hashes.SHA256()))
    def dynamic(label, size, partial_claim):
        da_calls.append((label, size, partial_claim))
        return b"\xa1\x63pad\x58\x39" + b"X" * 57
    original, _, _, context = sessions(claim_callback=claim, dynamic=dynamic)
    reservation = original.reserve_init_uuid()
    pending = original.export_state()
    assert claim_calls == da_calls == []
    restored, _, _, restored_context = sessions(claim_callback=claim, dynamic=dynamic)
    restored.import_state(pending)
    context.close()
    restored_context.close()
    gc.collect()
    final = restored.finalize_init_uuid(c2pa.trusted_vsi_hash_template(KIND.INIT_HASH))
    assert len(final) == len(reservation)
    assert len(da_calls) == 1 and len(claim_calls) >= 1
    assert da_calls[0][0:2] == ("com.example.functional", 64)


@pytest.mark.parametrize("field", ["sequence", "manifest", "iat", "binding_payload"])
def test_paired_expert_rejects_signed_identity_and_time_mismatch_without_callbacks(sessions, field):
    session, calls, _, _ = sessions()
    _init(session)
    before, count = session.export_state(), len(calls)
    tbs = _sig_structure(session=session, sequence=2 if field == "sequence" else 1,
                         iat=IAT + 86400 if field == "iat" else IAT)
    framing = cbor2.loads(tbs)
    if field == "manifest":
        payload = cbor2.loads(framing[3])
        payload["manifestId"] = "foreign-manifest"
        framing[3] = cbor2.dumps(payload)
    elif field == "binding_payload":
        framing[3] = cbor2.dumps(b"detached signerBinding certificate")
    tbs = cbor2.dumps(framing)
    # Static validation cannot know session identity or its validity window.
    if field == "binding_payload":
        with pytest.raises(c2pa.C2paError):
            c2pa.validate_trusted_vsi_input(KIND.SIG_STRUCTURE, "ed25519", tbs)
    else:
        c2pa.validate_trusted_vsi_input(KIND.SIG_STRUCTURE, "ed25519", tbs)
    with pytest.raises(c2pa.C2paError):
        session.preflight(OP.EXPERT_SIGN, tbs, sequence_number=1)
    with pytest.raises(c2pa.C2paError):
        session.sign_sig_structure(tbs, 1)
    assert session.export_state() == before and len(calls) == count
    assert not session.status().blocked


@pytest.mark.parametrize("version", [1, 2])
def test_paired_old_state_versions_rejected_before_mutation(sessions, version):
    original, _, _, _ = sessions()
    original.reserve_init_uuid()
    state = json.loads(original.export_state())
    assert state["version"] == 3
    state["version"] = version
    new, calls, _, _ = sessions()
    before = new.export_state()
    with pytest.raises(c2pa.C2paError):
        new.import_state(json.dumps(state).encode())
    assert new.export_state() == before and calls == []


@pytest.mark.parametrize("make_error", [None] + [p.values[0] for p in CALLBACK_FAILURES])
def test_scripted_reentrant_close_retains_thunks_until_free_and_then_collects(monkeypatch, make_error):
    native = _ScriptedNative(monkeypatch)
    certs = (FIXTURES / "es256_certs.pem").read_bytes()
    signer = c2pa.Signer.from_callback(_fixture_claim_signature, c2pa.C2paSigningAlg.ES256, certs, None)
    context = c2pa.Context(signer=signer)
    error = make_error() if make_error else None
    holder = {}

    def callback(ctx, data):
        session = holder["session"]
        session.close()
        session.close()
        assert not session.is_valid and session._handle is not None
        with pytest.raises(c2pa.C2paError, match="closed"):
            session.export_state()
        gc.collect()
        assert claim_ref() is not None and vsi_ref() is not None
        assert native.freed == []
        if error is not None:
            raise error
        return b"S" * 64

    native.install(monkeypatch, "session_create_callback_v1",
                   lambda *args: setattr(native, "callback", weakref.proxy(args[-1])) or native.handle)
    session = c2pa.TrustedVsiSession(
        context, {"format": "video/mp4"}, "es256", b"k", b"kid", 1,
        "2026-09-10T00:00:00Z", 86400, callback, mode="expert_sig_structure",
        reservation_nonce="0" * 32, signing_time_unix_seconds=IAT)
    holder["session"] = session
    claim_ref = weakref.ref(session._signer_callback_cb)
    vsi_ref = weakref.ref(session._trusted_vsi_callback[0])
    # Recorded constructor arguments would otherwise be artificial strong pins.
    native.calls.clear()
    context.close()
    real_free = bindings.ManagedResource._free_native_ptr

    def free(ptr):
        if ctypes.addressof(ptr.contents) == ctypes.addressof(native.handle.contents):
            assert session._trusted_vsi_callback is None  # _release already ran
            gc.collect()
            assert claim_ref() is not None and vsi_ref() is not None
        return real_free(ptr)
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", staticmethod(free))

    def sign(handle, data, length, sequence, output):
        result, signature = native.invoke()
        if error is not None:
            assert result == -1
            return -1
        assert result == 64
        return native.output(output, signature)
    native.install(monkeypatch, "session_sign_sig_structure", sign)
    if error is not None:
        with pytest.raises(type(error)) as caught:
            session.sign_sig_structure(b"tbs", 1)
        assert caught.value is error
        # Exception tracebacks legitimately retain callback frames.
        error.__traceback__ = None
        del caught
    else:
        assert session.sign_sig_structure(b"tbs", 1) == b"S" * 64
    session.close()
    assert native.freed.count(ctypes.addressof(native.handle.contents)) == 1
    gc.collect()
    assert claim_ref() is None and vsi_ref() is None


def test_call_guard_close_from_other_thread_is_nonblocking_and_drains_once(monkeypatch):
    resource = bindings.ManagedResource()
    resource._activate(ctypes.c_void_p(123))
    freed = Mock()
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    with resource._native_call():
        closer = threading.Thread(target=resource.close)
        closer.start()
        closer.join(timeout=2)
        assert not closer.is_alive(), "close must not wait for a callback/native call"
        assert not resource.is_valid and resource._handle is not None
        freed.assert_not_called()
        with pytest.raises(c2pa.C2paError, match="closed"):
            with resource._native_call():
                pytest.fail("closed resource admitted another operation")
    freed.assert_called_once()
    assert resource._handle is None
    resource.close()
    freed.assert_called_once()


def test_two_admitted_call_guards_close_and_staggered_drain(monkeypatch):
    # Exercise bookkeeping, not concurrent native operations (which require
    # external serialization even when both calls have a lifetime guard).
    resource = bindings.ManagedResource()
    handle = ctypes.c_void_p(123)
    resource._activate(handle)
    freed = Mock()
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    with resource._native_call():
        with resource._native_call():
            assert resource._active_calls == 2
            resource.close()
            assert not resource.is_valid and resource._handle is handle
            freed.assert_not_called()
        assert resource._active_calls == 1 and resource._handle is handle
        freed.assert_not_called()
    assert resource._active_calls == 0 and resource._handle is None
    freed.assert_called_once_with(handle)
    resource.close()
    freed.assert_called_once()


def test_release_handle_preserves_closed_pending_borrow(monkeypatch):
    resource = bindings.ManagedResource()
    handle = ctypes.c_void_p(123)
    resource._activate(handle)
    freed = Mock()
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    with resource._native_call():
        resource.close()
        resource._release_handle()
        assert resource._handle is handle and resource._pending_teardown is True
        assert resource._active_calls == 1 and not resource.is_valid
        freed.assert_not_called()
    assert resource._handle is None and resource._pending_teardown is None
    freed.assert_called_once_with(handle)


def test_call_guard_foreign_pid_drain_never_locks_releases_or_frees(monkeypatch):
    resource = bindings.ManagedResource()
    resource._activate(ctypes.c_void_p(123))
    freed = Mock()
    release = Mock()
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    resource._release = release
    with resource._native_call():
        resource.close()
        resource._owner_pid = os.getpid() + 1
        # A copied lock might have belonged to a vanished thread at fork.
        resource._call_lock = Mock(side_effect=AssertionError("foreign lock touched"))
    assert not resource.is_valid and resource._handle is None
    release.assert_not_called()
    freed.assert_not_called()


def test_call_guard_foreign_pid_admission_rejects_before_lock_or_ffi_without_cleanup(monkeypatch):
    resource = bindings.Signer._wrap_native_handle(ctypes.pointer(bindings.C2paSigner()))
    handle, parent_pid, parent_lock = resource._handle, resource._owner_pid, resource._call_lock
    callback_pin = bindings.SignerCallback(lambda *args: -1)
    resource._callback_cb = callback_pin
    dynamic_pins = resource._dynamic_assertion_cbs
    dynamic_pins.append((bindings.DynamicAssertionCallback(lambda *args: -1),
                         threading.local(), lambda *args: b""))
    dynamic_pin = dynamic_pins[0]
    freed, release, ffi = Mock(), Mock(), Mock()
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    monkeypatch.setattr(resource, "_release", release)

    class InheritedLock:
        def __enter__(self):
            raise AssertionError("foreign admission touched an inherited lock")

        def __exit__(self, *args):
            raise AssertionError("foreign admission touched an inherited lock")

    resource._owner_pid = parent_pid + 1
    resource._call_lock = InheritedLock()
    try:
        with pytest.raises(c2pa.C2paError, match="after fork"):
            with resource._native_call():
                ffi(handle)
        ffi.assert_not_called()
        release.assert_not_called()
        freed.assert_not_called()
        assert resource.is_valid and resource._handle is handle
        assert resource._active_calls == 0 and resource._pending_teardown is None
        assert resource._callback_cb is callback_pin
        assert resource._dynamic_assertion_cbs is dynamic_pins
        assert dynamic_pins == [dynamic_pin]
    finally:
        # Restore the simulated parent's identity/lock for its own cleanup.
        resource._owner_pid, resource._call_lock = parent_pid, parent_lock
        resource.close()


def test_consumed_teardown_inside_call_guard_retains_pins_then_releases_without_free(monkeypatch):
    # Bookkeeping-only: actual consuming FFI operations still require external
    # serialization and must not consume a handle another native call borrows.
    resource = bindings.Builder._wrap_native_handle(ctypes.pointer(bindings.C2paBuilder()))
    handle = resource._handle
    callback_pin = bindings.SignerCallback(lambda *args: -1)
    resource._signer_callback_cb = callback_pin
    dynamic_pin = (bindings.DynamicAssertionCallback(lambda *args: -1),
                   threading.local(), lambda *args: b"")
    resource._dynamic_assertion_cbs.append(dynamic_pin)
    freed = Mock()
    release = Mock(wraps=resource._release)
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    monkeypatch.setattr(resource, "_release", release)
    with resource._native_call():
        resource._teardown(free_handle=False)
        resource.close()
        resource._release_handle()
        assert not resource.is_valid and resource._handle is handle
        assert resource._pending_teardown is False and resource._active_calls == 1
        assert resource._signer_callback_cb is callback_pin
        assert resource._dynamic_assertion_cbs == [dynamic_pin]
        release.assert_not_called()
        freed.assert_not_called()
    assert resource._handle is None and resource._pending_teardown is None
    assert resource._active_calls == 0 and not resource.is_valid
    assert resource._signer_callback_cb is None and resource._dynamic_assertion_cbs == []
    release.assert_called_once()
    resource.close()
    release.assert_called_once()
    freed.assert_not_called()


def test_teardown_copies_dynamic_thunks_through_release_and_free(monkeypatch):
    resource = bindings.Builder._wrap_native_handle(ctypes.pointer(bindings.C2paBuilder()))
    resource._dynamic_assertion_cbs.append((
        bindings.DynamicAssertionCallback(lambda *args: -1), threading.local(), lambda *args: b""))
    callback_ref = weakref.ref(resource._dynamic_assertion_cbs[0][0])

    def free(ptr):
        assert resource._dynamic_assertion_cbs == []
        gc.collect()
        assert callback_ref() is not None
        return 0
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", staticmethod(free))
    resource.close()
    gc.collect()
    assert callback_ref() is None


def _actual_native_reentrant_close(kind):
    """Executed only in a subprocess: a stale ctypes thunk can crash Python."""
    certs = (FIXTURES / "es256_certs.pem").read_bytes()
    seen, churn, holder = [], [], {}
    manifest = {"claim_version": 2, "assertions": [{"label": "c2pa.actions", "data": {
        "actions": [{"action": "c2pa.created", "digitalSourceType":
                     "http://c2pa.org/digitalsourcetype/empty"}]}}]}

    def impostor(*args):
        seen.append("IMPOSTOR")
        return -1

    def close_and_churn():
        holder["resource"].close()
        if "signer" in holder:
            holder["signer"].close()
        gc.collect()
        churn.extend(bindings.SignerCallback(impostor) for _ in range(512))

    def claim(data):
        seen.append("claim")
        if kind.startswith("builder"):
            if kind == "builder_context_callback_close":
                holder["context"].close()
                assert not holder["context"].is_valid
            close_and_churn()
        return _fixture_claim_signature(data)

    signer = c2pa.Signer.from_callback(claim, c2pa.C2paSigningAlg.ES256, certs, None)
    if kind.startswith("builder"):
        if kind == "builder_explicit":
            builder = c2pa.Builder(manifest)
            holder["signer"] = signer
        else:
            context = c2pa.Context(signer=signer)
            builder = c2pa.Builder(manifest, context=context)
            if kind == "builder_context_callback_close":
                holder["context"] = context
            else:
                context.close()
        holder["resource"] = builder
        source = io.BytesIO((FIXTURES / "A.jpg").read_bytes())
        dest = io.BytesIO()
        result = (builder.sign(signer, "image/jpeg", source, dest)
                  if kind == "builder_explicit" else builder.sign("image/jpeg", source, dest))
        assert result and dest.getvalue() and not builder.is_valid
        signer.close()
    else:
        config = json.loads((Path(__file__).parent / "trust_config_test_settings.json").read_text())
        context = c2pa.Context.from_dict(config, signer=signer)
        key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        cose = cbor2.dumps({1: 1, 2: b"kid", 3: -8, -1: 6, -2: public}, canonical=True)

        def vsi(*args):
            seen.append("binding")
            close_and_churn()
            return key.sign(args[-1])

        if kind == "trusted":
            resource = c2pa.TrustedVsiSession(
                context, manifest, "ed25519", cose, b"kid", 1,
                "2026-09-10T00:00:00Z", 86400, vsi, mode="expert_sig_structure",
                reservation_nonce="0" * 32, signing_time_unix_seconds=IAT)
            resource.reserve_init_uuid()
        else:
            resource = c2pa.LiveVideoVsiSession.from_callback(
                manifest, context, vsi, "ed25519", cose,
                b"kid", 1, "2026-09-10T00:00:00Z", 86400, clock=lambda: IAT)
        holder["resource"] = resource
        context.close()
        if kind == "trusted":
            result = resource.finalize_init_uuid(c2pa.trusted_vsi_hash_template(KIND.INIT_HASH))
        else:
            result = resource.sign_init_segment(_unsigned_init())
        assert result and not resource.is_valid
        assert seen[0] == "binding"
        resource.close()
    assert "claim" in seen and "IMPOSTOR" not in seen
    print("actual native reentrant close:", kind, seen)


def _check_native_reentrant_close_subprocess(kind):
    result = subprocess.run(
        [sys.executable, "-c", "from tests.test_trusted_vsi_api import _actual_native_reentrant_close; "
         f"_actual_native_reentrant_close({kind!r})"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "actual native reentrant close:" in result.stdout


@pytest.mark.parametrize("kind", ["trusted", "live"])
def test_paired_reentrant_close_native_subprocess(paired_native, kind):
    _check_native_reentrant_close_subprocess(kind)


@pytest.mark.parametrize("kind", ["builder_context", "builder_explicit", "builder_context_callback_close"])
def test_builder_reentrant_close_native_subprocess(kind):
    _check_native_reentrant_close_subprocess(kind)


@pytest.mark.parametrize("kind", ["ordinary", "fragmented", "ladder"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_builder_borrowed_signer_reentrant_close_and_automatic_close(monkeypatch, tmp_path, kind, interrupt):
    """Scripted native call: both borrowed handles survive callback close."""
    error = SystemExit(7)
    holder = {}

    def claim(data):
        holder["builder"].close()
        holder["signer"].close()
        if interrupt:
            raise error
        return _fixture_claim_signature(data)

    signer = c2pa.Signer.from_callback(claim, c2pa.C2paSigningAlg.ES256,
                                      (FIXTURES / "es256_certs.pem").read_bytes(), None)
    builder = c2pa.Builder({})
    holder.update(builder=builder, signer=signer)
    builder_handle, signer_handle = builder._handle, signer._handle
    freed = []
    real_free = bindings.ManagedResource._free_native_ptr

    def free(ptr):
        freed.append(ctypes.cast(ptr, ctypes.c_void_p).value)
        return real_free(ptr)
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", staticmethod(free))
    callback_ref = weakref.ref(signer._callback_cb)

    def sign(*args):
        tbs = (ctypes.c_ubyte * 3)(1, 2, 3)
        signature = (ctypes.c_ubyte * 2048)()
        result = signer._callback_cb(None, tbs, 3, signature, len(signature))
        gc.collect()
        assert builder._handle is builder_handle and signer._handle is signer_handle
        assert not builder.is_valid and not signer.is_valid
        assert freed == [] and callback_ref() is not None
        if interrupt:
            assert result == -1
            return -1
        assert result > 0
        # Failure without a callback error is sufficient to exercise cleanup;
        # no fake byte allocation should reach the real native deallocator.
        return -1

    monkeypatch.setattr(bindings, "_read_native_error", lambda: "Other: scripted signing failure")
    if kind == "ordinary":
        monkeypatch.setattr(bindings._lib, "c2pa_builder_sign", sign)
        operation = lambda: builder.sign(signer, "image/jpeg", io.BytesIO(b"input"), io.BytesIO())
    elif kind == "fragmented":
        monkeypatch.setattr(bindings, "_FRAGMENTED_SIGN_AVAILABLE", True)
        monkeypatch.setattr(bindings._lib, "c2pa_builder_sign_fragmented", sign, raising=False)
        source = tmp_path / "init.mp4"
        source.write_bytes(b"input")
        operation = lambda: builder.sign_fragmented(signer, source, "*.m4s", tmp_path)
    else:
        monkeypatch.setattr(bindings, "_HAS_SIGN_LADDER", True)
        monkeypatch.setattr(bindings._lib, "c2pa_builder_sign_ladder", sign, raising=False)
        operation = lambda: builder.sign_ladder(signer, ["input.mp4"], ["output.mp4"])
    with pytest.raises(SystemExit if interrupt else c2pa.C2paError) as caught:
        operation()
    if interrupt:
        assert caught.value is error
        error.__traceback__ = None
    del caught
    assert builder._handle is None and signer._handle is None
    for handle in (builder_handle, signer_handle):
        assert freed.count(ctypes.cast(handle, ctypes.c_void_p).value) == 1
    builder.close()
    signer.close()
    gc.collect()
    assert callback_ref() is None


@pytest.mark.parametrize("kind", ["ordinary", "fragmented", "ladder"])
@pytest.mark.parametrize("when", ["preflight", "admission", "interrupted_admission"])
def test_builder_rejects_logically_closed_signer_preflight_or_admission(monkeypatch, tmp_path, kind, when):
    builder = bindings.Builder._wrap_native_handle(ctypes.pointer(bindings.C2paBuilder()))
    signer = bindings.Signer._wrap_native_handle(ctypes.pointer(bindings.C2paSigner()))
    handle = signer._handle
    freed = Mock(return_value=0)
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    native = Mock(side_effect=AssertionError("closed Signer reached native signing"))
    interruption = KeyboardInterrupt("admission interrupted")
    if kind == "ordinary":
        monkeypatch.setattr(bindings._lib, "c2pa_builder_sign", native)
        operation = lambda: builder.sign(signer, "image/jpeg", io.BytesIO(b"input"), io.BytesIO())
    elif kind == "fragmented":
        monkeypatch.setattr(bindings, "_FRAGMENTED_SIGN_AVAILABLE", True)
        monkeypatch.setattr(bindings._lib, "c2pa_builder_sign_fragmented", native, raising=False)
        source = tmp_path / "init.mp4"
        source.write_bytes(b"input")
        operation = lambda: builder.sign_fragmented(signer, source, "*.m4s", tmp_path)
    else:
        monkeypatch.setattr(bindings, "_HAS_SIGN_LADDER", True)
        monkeypatch.setattr(bindings._lib, "c2pa_builder_sign_ladder", native, raising=False)
        operation = lambda: builder.sign_ladder(signer, ["input.mp4"], ["output.mp4"])
    try:
        # A simulated close between preflight and call admission, not permission
        # to run concurrent native operations on the borrowed Signer.
        with signer._native_call():
            if when == "preflight":
                signer.close()
            else:
                admit = signer._native_call

                def close_then_admit():
                    signer.close()
                    if when == "interrupted_admission":
                        raise interruption
                    return admit()
                monkeypatch.setattr(signer, "_native_call", close_then_admit)
            expected = KeyboardInterrupt if when == "interrupted_admission" else c2pa.C2paError
            with pytest.raises(expected) as caught:
                operation()
            if when == "interrupted_admission":
                assert caught.value is interruption
            else:
                assert "closed" in str(caught.value)
            native.assert_not_called()
            assert not signer.is_valid and signer._handle is handle
            assert builder.is_valid is (when == "preflight")
            assert freed.call_count == (0 if when == "preflight" else 1)
        assert signer._handle is None
    finally:
        builder.close()
        signer.close()
    assert freed.call_count == 2


def test_builder_bad_format_preflight_keeps_builder_and_signer_active(monkeypatch):
    builder = bindings.Builder._wrap_native_handle(ctypes.pointer(bindings.C2paBuilder()))
    signer = bindings.Signer._wrap_native_handle(ctypes.pointer(bindings.C2paSigner()))
    freed = Mock(return_value=0)
    monkeypatch.setattr(bindings.ManagedResource, "_free_native_ptr", freed)
    native = Mock(side_effect=AssertionError("bad format reached native signing"))
    monkeypatch.setattr(bindings._lib, "c2pa_builder_sign", native)
    try:
        with pytest.raises(c2pa.C2paError.NotSupported):
            builder.sign(signer, "", io.BytesIO(b"input"), io.BytesIO())
        assert builder.is_valid and signer.is_valid
        assert builder._active_calls == signer._active_calls == 0
        native.assert_not_called()
        freed.assert_not_called()
    finally:
        builder.close()
        signer.close()
