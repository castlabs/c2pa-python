"""Offset-aware single-file fragment verification (Castlabs native API).

Scripted tests exercise Python gating, argument validation and marshalling
without the native entry point (they delegate to ``c2pa_reader_with_fragment``,
which every supported native library exports). Tests marked ``real native``
need ``c2pa_reader_with_fragment_at_offset``: they skip when the loaded library
lacks it, and FAIL instead under ``C2PA_FRAGMENT_OFFSET_REQUIRED=1``.
"""

import ctypes
import gc
import io
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

import c2pa
import c2pa.c2pa as bindings
from c2pa import C2paError, Context, Reader, Settings


FIXTURES = Path(__file__).parent / "fixtures"
SIDX_FIXTURE = FIXTURES / "single-file-fragmented" / "single_file_fragments_sidx.mp4"
C2PA_BOX_UUID = bytes([
    0xd8, 0xfe, 0xc3, 0xd6, 0x1b, 0x0e, 0x48, 0x3c,
    0x92, 0x97, 0x58, 0x28, 0x87, 0x7e, 0xc4, 0x81,
])
MATCH = "assertion.bmffHash.match"
MISMATCH = "assertion.bmffHash.mismatch"
U64_MAX = 2**64 - 1


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _forbid_native(monkeypatch):
    """Replace _lib and Context so any native touch fails the test."""
    forbidden = Mock(side_effect=AssertionError("native touched"))
    monkeypatch.setattr(bindings, "_lib", forbidden)
    monkeypatch.setattr(bindings, "Context", forbidden)
    return forbidden


def _enable_gate(monkeypatch):
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_SYMBOLS_AVAILABLE", True)
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_PROBE", True)


def _signed_reader():
    """A real Reader over a signed asset (no offset API involved)."""
    return Reader(str(FIXTURES / "C.jpg"))


def _trust_context():
    settings = Settings.from_dict(json.loads(
        (Path(__file__).parent / "trust_config_test_settings.json").read_text()))
    try:
        return Context(settings=settings)
    finally:
        settings.close()


def _merkle_uuid_starts(data: bytes):
    """Start offsets of root C2PA ``merkle`` uuid boxes, in file order."""
    starts, pos = [], 0
    while pos + 8 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        header = 8
        if size == 0:
            size = len(data) - pos
        elif size == 1:
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
            header = 16
        assert header <= size and pos + size <= len(data), f"bad box at {pos}"
        payload = pos + header
        if (kind == b"uuid" and pos + size >= payload + 16 + 4 + 7
                and data[payload:payload + 16] == C2PA_BOX_UUID
                and data[payload + 20:payload + 27] == b"merkle\0"):
            starts.append(pos)
        pos += size
    return starts


def _codes(reader, kind):
    results = reader.get_validation_results() or {}
    active = results.get("activeManifest") or {}
    return {entry.get("code") for entry in active.get(kind, [])}


# --------------------------------------------------------------------------
# Gating
# --------------------------------------------------------------------------

def test_exported_from_package():
    assert c2pa.has_fragment_at_offset is bindings.has_fragment_at_offset
    assert "has_fragment_at_offset" in c2pa.__all__
    assert "has_fragment_at_offset" in bindings.__all__
    assert bindings._FRAGMENT_AT_OFFSET_FUNCTIONS == (
        "c2pa_reader_with_fragment_at_offset",
        "c2pa_reader_fragment_at_offset_supported",
    )
    # Optional: never part of the import-time required export set.
    for name in bindings._FRAGMENT_AT_OFFSET_FUNCTIONS:
        assert name not in bindings._REQUIRED_FUNCTIONS


@pytest.mark.parametrize("symbols, probe, expected", [
    (False, False, False),
    (False, True, False),
    (True, False, False),
    (True, True, True),
])
def test_gate_requires_symbols_and_probe(monkeypatch, symbols, probe, expected):
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_SYMBOLS_AVAILABLE", symbols)
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_PROBE", probe)
    assert c2pa.has_fragment_at_offset() is expected


def test_gate_matches_loaded_library():
    present = all(hasattr(bindings._lib, name)
                  for name in bindings._FRAGMENT_AT_OFFSET_FUNCTIONS)
    assert bindings._FRAGMENT_AT_OFFSET_SYMBOLS_AVAILABLE is present
    if not present:
        assert c2pa.has_fragment_at_offset() is False
        assert bindings._FRAGMENT_AT_OFFSET_PROBE is None, "probe never called"


@pytest.mark.parametrize("native_result", [True, False])
def test_probe_is_lazy_and_cached(monkeypatch, native_result):
    calls = []

    class Library:
        def c2pa_reader_fragment_at_offset_supported(self):
            calls.append(1)
            return native_result
    monkeypatch.setattr(bindings, "_lib", Library())
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_SYMBOLS_AVAILABLE", True)
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_PROBE", None)
    assert c2pa.has_fragment_at_offset() is native_result
    assert c2pa.has_fragment_at_offset() is native_result
    assert calls == [1]


def test_missing_symbols_never_call_probe(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("probe called"))
    monkeypatch.setattr(bindings, "_lib", forbidden)
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_SYMBOLS_AVAILABLE", False)
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_PROBE", None)
    assert c2pa.has_fragment_at_offset() is False
    assert forbidden.mock_calls == []


@pytest.mark.parametrize("symbols, probe", [(False, False), (True, False), (False, True)])
def test_unavailable_classmethod_raises_before_arguments_or_native(
        monkeypatch, symbols, probe):
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_SYMBOLS_AVAILABLE", symbols)
    monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_PROBE", probe)
    forbidden = _forbid_native(monkeypatch)
    # Arguments are deliberately invalid: gating must come first.
    with pytest.raises(C2paError.NotSupported, match="fragment"):
        Reader.from_fragment_at_offset(5, object(), object(), -1, context=object())
    assert forbidden.mock_calls == []


def test_unavailable_instance_method_leaves_reader_unchanged(monkeypatch):
    reader = _signed_reader()
    try:
        handle = reader._handle
        json_before = reader.json()
        monkeypatch.setattr(bindings, "_FRAGMENT_AT_OFFSET_PROBE", False)
        real_lib = bindings._lib
        forbidden = _forbid_native(monkeypatch)
        with pytest.raises(C2paError.NotSupported):
            reader.with_fragment_at_offset(
                "video/mp4", io.BytesIO(b"a"), io.BytesIO(b"b"), 0)
        assert forbidden.mock_calls == []
        monkeypatch.setattr(bindings, "_lib", real_lib)
        assert reader.is_valid
        assert reader._handle is handle
        assert reader.json() == json_before
    finally:
        reader.close()


# --------------------------------------------------------------------------
# Argument validation (gate forced open, native forbidden)
# --------------------------------------------------------------------------

def _valid_args():
    return ["video/mp4", io.BytesIO(b"init"), io.BytesIO(b"fragment"), 0]


BAD_ARGS = [
    pytest.param(3, -1, ValueError, id="negative-offset"),
    pytest.param(3, 2**64, ValueError, id="offset-over-u64"),
    pytest.param(3, True, TypeError, id="bool-offset"),
    pytest.param(3, 1.0, TypeError, id="float-offset"),
    pytest.param(3, "0", TypeError, id="str-offset"),
    pytest.param(3, None, TypeError, id="none-offset"),
    pytest.param(0, b"video/mp4", TypeError, id="bytes-format"),
    pytest.param(0, 7, TypeError, id="int-format"),
    pytest.param(0, "video/mp4\0x", ValueError, id="nul-format"),
    pytest.param(0, None, TypeError, id="none-format"),
    pytest.param(0, "", ValueError, id="empty-format"),
    pytest.param(0, "  ", ValueError, id="blank-format"),
    pytest.param(1, object(), TypeError, id="non-stream-init"),
    pytest.param(1, "init.mp4", TypeError, id="path-init"),
    pytest.param(2, b"fragment", TypeError, id="bytes-fragment"),
    pytest.param(2, None, TypeError, id="none-fragment"),
]


@pytest.mark.parametrize("index, value, error", BAD_ARGS)
def test_classmethod_rejects_invalid_arguments_before_native(
        monkeypatch, index, value, error):
    _enable_gate(monkeypatch)
    forbidden = _forbid_native(monkeypatch)
    args = _valid_args()
    args[index] = value
    with pytest.raises(error):
        Reader.from_fragment_at_offset(*args)
    assert forbidden.mock_calls == []


def test_classmethod_rejects_same_stream_object(monkeypatch):
    _enable_gate(monkeypatch)
    forbidden = _forbid_native(monkeypatch)
    shared = io.BytesIO(b"x")
    with pytest.raises(ValueError, match="distinct"):
        Reader.from_fragment_at_offset("video/mp4", shared, shared, 0)
    assert forbidden.mock_calls == []


@pytest.mark.parametrize("context", [object(), "context"])
def test_classmethod_rejects_non_context(monkeypatch, context):
    _enable_gate(monkeypatch)
    forbidden = _forbid_native(monkeypatch)
    with pytest.raises(TypeError, match="ContextProvider"):
        Reader.from_fragment_at_offset(*_valid_args(), context=context)
    assert forbidden.mock_calls == []


def test_classmethod_rejects_closed_context(monkeypatch):
    context = Context()
    context.close()
    _enable_gate(monkeypatch)
    forbidden = _forbid_native(monkeypatch)
    with pytest.raises(C2paError, match="Context is not valid"):
        Reader.from_fragment_at_offset(*_valid_args(), context=context)
    assert forbidden.mock_calls == []


@pytest.mark.parametrize("index, value, error", BAD_ARGS)
def test_instance_method_rejects_invalid_arguments_and_keeps_reader(
        monkeypatch, index, value, error):
    reader = _signed_reader()
    try:
        handle = reader._handle
        _enable_gate(monkeypatch)
        real_lib = bindings._lib
        forbidden = _forbid_native(monkeypatch)
        args = _valid_args()
        args[index] = value
        with pytest.raises(error):
            reader.with_fragment_at_offset(*args)
        shared = io.BytesIO(b"x")
        with pytest.raises(ValueError, match="distinct"):
            reader.with_fragment_at_offset("video/mp4", shared, shared, 0)
        assert forbidden.mock_calls == []
        monkeypatch.setattr(bindings, "_lib", real_lib)
        assert reader.is_valid and reader._handle is handle
        assert reader.json()
    finally:
        reader.close()


def test_instance_method_on_closed_reader_raises(monkeypatch):
    _enable_gate(monkeypatch)
    reader = _signed_reader()
    reader.close()
    with pytest.raises(C2paError, match="closed"):
        reader.with_fragment_at_offset(*_valid_args())


# --------------------------------------------------------------------------
# Scripted marshalling: the scripted entry point records its arguments and
# delegates to the real c2pa_reader_with_fragment (same ownership contract).
# --------------------------------------------------------------------------

class _ScriptedOffsetCall:
    def __init__(self, monkeypatch):
        self.calls = []
        _enable_gate(monkeypatch)
        real = bindings._lib.c2pa_reader_with_fragment

        def call(handle, fmt, stream, fragment, offset):
            self.calls.append((fmt, stream, fragment, offset))
            return real(handle, fmt, stream, fragment)
        monkeypatch.setattr(
            bindings._lib, "c2pa_reader_with_fragment_at_offset", call,
            raising=False)


def _dash_streams():
    return (io.BytesIO((FIXTURES / "dashinit.mp4").read_bytes()),
            io.BytesIO((FIXTURES / "dash1.m4s").read_bytes()))


@pytest.mark.parametrize("offset", [0, 1, 2**32, U64_MAX])
def test_scripted_classmethod_marshals_offset_and_pins_context(monkeypatch, offset):
    scripted = _ScriptedOffsetCall(monkeypatch)
    init, fragment = _dash_streams()
    context = Context()
    try:
        with Reader.from_fragment_at_offset(
                " Video/MP4 ", init, fragment, offset, context=context) as reader:
            assert reader.is_valid
            assert reader._context is context
            assert reader.json()
    finally:
        context.close()
    assert len(scripted.calls) == 1
    fmt, stream, frag, seen_offset = scripted.calls[0]
    assert fmt == b"video/mp4"
    assert seen_offset == offset
    assert ctypes.cast(stream, ctypes.c_void_p).value != ctypes.cast(
        frag, ctypes.c_void_p).value


def test_scripted_classmethod_without_context_uses_default_context(monkeypatch):
    scripted = _ScriptedOffsetCall(monkeypatch)
    created = []
    real_context = bindings.Context

    def tracking_context(*args, **kwargs):
        context = real_context(*args, **kwargs)
        created.append(context)
        return context
    monkeypatch.setattr(bindings, "Context", tracking_context)
    init, fragment = _dash_streams()
    with Reader.from_fragment_at_offset("video/mp4", init, fragment, 7) as reader:
        assert reader.json()
        assert reader._context is None
    assert len(created) == 1 and not created[0].is_valid, \
        "the temporary default Context must be released"
    assert scripted.calls[0][3] == 7


def test_scripted_instance_method_swaps_handle_and_clears_caches(monkeypatch):
    scripted = _ScriptedOffsetCall(monkeypatch)
    with Context() as context:
        init, fragment = _dash_streams()
        with Reader("video/mp4", io.BytesIO(init.getvalue()), context=context) as reader:
            reader.json()
            reader._manifest_data_cache = {"stale": True}
            result = reader.with_fragment_at_offset(
                "video/mp4", init, fragment, 1234)
            assert result is reader
            assert reader.is_valid
            assert reader._manifest_data_cache is None
            assert reader._manifest_json_str_cache is None
            assert reader.json()
    assert scripted.calls[0][3] == 1234


def test_scripted_native_failure_closes_instance_reader(monkeypatch):
    scripted = _ScriptedOffsetCall(monkeypatch)
    with Context() as context:
        init, fragment = _dash_streams()
        reader = Reader("video/mp4", io.BytesIO(init.getvalue()), context=context)
        # An init stream without a manifest fails after native took the reader.
        with pytest.raises(C2paError):
            reader.with_fragment_at_offset(
                "video/mp4", io.BytesIO(b"\0" * 8), fragment, 0)
        assert not reader.is_valid
        reader.close()
    assert len(scripted.calls) == 1


def test_scripted_native_failure_from_classmethod_raises_without_reader(monkeypatch):
    _ScriptedOffsetCall(monkeypatch)
    created = []
    real_wrap = bindings.Reader._wrap_native_handle.__func__

    def tracking_wrap(cls, handle):
        reader = real_wrap(cls, handle)
        created.append(reader)
        return reader
    monkeypatch.setattr(bindings.Reader, "_wrap_native_handle",
                        classmethod(tracking_wrap))
    _, fragment = _dash_streams()
    with Context() as context:
        with pytest.raises(C2paError):
            Reader.from_fragment_at_offset(
                "video/mp4", io.BytesIO(b"\0" * 8), fragment, 0, context=context)
    assert len(created) == 1
    assert not created[0].is_valid
    assert created[0]._context is None, "failed reader must release its pins"


# --------------------------------------------------------------------------
# Real native
# --------------------------------------------------------------------------

def _require_native():
    if c2pa.has_fragment_at_offset():
        return
    if os.environ.get("C2PA_FRAGMENT_OFFSET_REQUIRED") == "1":
        pytest.fail("C2PA_FRAGMENT_OFFSET_REQUIRED=1 but the loaded native "
                    "library lacks c2pa_reader_with_fragment_at_offset or its "
                    "probe")
    pytest.skip("native library lacks offset-aware fragment verification")


_DEFINITION = {
    "claim_generator_info": [{"name": "fragment-at-offset-test", "version": "0.0.1"}],
    "title": "fragment at offset",
    "assertions": [{"label": "c2pa.actions", "data": {"actions": [{
        "action": "c2pa.created",
        "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
    }]}}],
}


@pytest.fixture(scope="module")
def signed_cut():
    """Sign the per-fragment-sidx fixture; cut it merkle uuid to merkle uuid."""
    source = SIDX_FIXTURE.read_bytes()  # Missing committed data is never a skip.
    _require_native()
    info = c2pa.C2paSignerInfo(
        alg=b"es256", sign_cert=(FIXTURES / "es256_certs.pem").read_bytes(),
        private_key=(FIXTURES / "es256_private.key").read_bytes(), ta_url=None)
    dest = io.BytesIO()
    with c2pa.Signer.from_info(info) as signer, \
            c2pa.Builder(_DEFINITION) as builder:
        builder.sign(signer, "video/mp4", io.BytesIO(source), dest)
    signed = dest.getvalue()
    starts = _merkle_uuid_starts(signed)
    assert len(starts) >= 2, f"expected several merkle uuid boxes, got {starts}"
    init = signed[:starts[0]]
    segments = [(start, signed[start:(starts[i + 1] if i + 1 < len(starts)
                                      else len(signed))])
                for i, start in enumerate(starts)]
    return signed, init, segments


@pytest.fixture
def trust_context():
    context = _trust_context()
    yield context
    context.close()


def test_real_native_export_signatures():
    _require_native()
    call = bindings._lib.c2pa_reader_with_fragment_at_offset
    assert call.argtypes == [
        ctypes.POINTER(bindings.C2paReader), ctypes.c_char_p,
        ctypes.POINTER(bindings.C2paStream), ctypes.POINTER(bindings.C2paStream),
        ctypes.c_uint64]
    assert call.restype is ctypes.POINTER(bindings.C2paReader)
    probe = bindings._lib.c2pa_reader_fragment_at_offset_supported
    assert probe.argtypes == [] and probe.restype is ctypes.c_bool
    assert probe() is True


def test_real_native_whole_file_is_trusted(signed_cut, trust_context):
    signed, _, _ = signed_cut
    with Reader("video/mp4", io.BytesIO(signed), context=trust_context) as reader:
        assert reader.get_validation_state() == "Trusted", reader.json()


def test_real_native_each_segment_verifies_at_its_offset(signed_cut, trust_context):
    _, init, segments = signed_cut
    for offset, segment in segments:
        with Reader.from_fragment_at_offset(
                "video/mp4", io.BytesIO(init), io.BytesIO(segment), offset,
                context=trust_context) as reader:
            assert reader.get_validation_state() == "Trusted", (offset, reader.json())
            assert MATCH in _codes(reader, "success"), (offset, reader.json())
            assert MISMATCH not in _codes(reader, "failure")


def test_real_native_segments_valid_without_trust_anchors(signed_cut):
    _, init, segments = signed_cut
    offset, segment = segments[-1]
    with Reader.from_fragment_at_offset(
            "video/mp4", io.BytesIO(init), io.BytesIO(segment), offset) as reader:
        assert reader.get_validation_state() == "Valid", reader.json()
        assert MATCH in _codes(reader, "success")


def test_real_native_wrong_offset_reports_mismatch(signed_cut, trust_context):
    _, init, segments = signed_cut
    offset, segment = segments[1]
    other_offset = segments[0][0]
    for wrong in (0, offset + 1, offset - 1, other_offset):
        with Reader.from_fragment_at_offset(
                "video/mp4", io.BytesIO(init), io.BytesIO(segment), wrong,
                context=trust_context) as reader:
            assert reader.get_validation_state() == "Invalid", (wrong, reader.json())
            assert MISMATCH in _codes(reader, "failure"), (wrong, reader.json())


def test_real_native_instance_method_on_context_reader(signed_cut, trust_context):
    signed, init, segments = signed_cut
    offset, segment = segments[-1]
    with Reader("video/mp4", io.BytesIO(signed), context=trust_context) as reader:
        assert reader.with_fragment_at_offset(
            "video/mp4", io.BytesIO(init), io.BytesIO(segment), offset) is reader
        assert reader.get_validation_state() == "Trusted", reader.json()
        assert MATCH in _codes(reader, "success")
        assert reader.with_fragment_at_offset(
            "video/mp4", io.BytesIO(init), io.BytesIO(segment), offset + 1) is reader
        assert reader.get_validation_state() == "Invalid"
        assert MISMATCH in _codes(reader, "failure")


def test_real_native_unsigned_init_raises_and_closes(signed_cut, trust_context):
    _, _, segments = signed_cut
    offset, segment = segments[0]
    with pytest.raises(C2paError):
        Reader.from_fragment_at_offset(
            "video/mp4", io.BytesIO(b"\0" * 8), io.BytesIO(segment), offset,
            context=trust_context)
    reader = Reader("video/mp4", io.BytesIO(signed_cut[0]), context=trust_context)
    with pytest.raises(C2paError):
        reader.with_fragment_at_offset(
            "video/mp4", io.BytesIO(b"\0" * 8), io.BytesIO(segment), offset)
    assert not reader.is_valid
    reader.close()
    gc.collect()
