"""Ownership triage for consuming FFI calls against the opaque-handle registry.

Consume-first native calls (Reader/Builder ``with_*``) untrack the managed
handle before validating their other arguments, so a registry rejection of a
different argument arrives after the managed handle was already dropped. These
tests use the real native library; only the rejected *argument* is synthetic.
"""

import ctypes
import io
import json
import os
from pathlib import Path

import pytest

import c2pa.c2pa as binding
from c2pa import Builder, C2paError, Context, Reader, Signer, C2paSignerInfo
from c2pa.c2pa import LifecycleState, ManagedResource

FIXTURES = Path(__file__).parent / "fixtures"


def _addr(pointer):
    return ctypes.cast(pointer, ctypes.c_void_p).value


def _untracked_stream():
    # Never handed out by the registry, so every lookup rejects it by address.
    buffer = ctypes.create_string_buffer(64)
    return ctypes.cast(buffer, ctypes.POINTER(binding.C2paStream)), buffer


@pytest.fixture(autouse=True)
def _clear_native_error_slot():
    # These tests plant or provoke registry errors; the slot is sticky and
    # thread-local, so a stale tag must not follow later tests around.
    yield
    binding._lib.c2pa_error_set_last(b"Other: cleared by test teardown")


@pytest.fixture
def reader():
    with open(FIXTURES / "dashinit.mp4", "rb") as init:
        value = Reader("video/mp4", init)
    yield value
    value.close()


@pytest.fixture
def frees(monkeypatch):
    calls = []
    real_free = ManagedResource._free_native_ptr

    def record(pointer):
        calls.append(_addr(pointer))
        return real_free(pointer)

    monkeypatch.setattr(ManagedResource, "_free_native_ptr", staticmethod(record))
    return calls


def _assert_closed(resource):
    assert resource._handle is None
    assert resource._lifecycle_state == LifecycleState.CLOSED
    resource.close()
    resource.close()


def _still_tracked(handle_value):
    """Return whether the registry still tracks a handle id (frees it if so)."""
    return binding._lib.c2pa_free(ctypes.c_void_p(handle_value)) == 0


def test_rejected_fragment_stream_after_reader_consumed_closes_reader(
        reader, monkeypatch, frees):
    consumed = reader._handle_value()
    bogus, _keep = _untracked_stream()
    real_call = binding._lib.c2pa_reader_with_fragment
    monkeypatch.setattr(
        binding._lib, "c2pa_reader_with_fragment",
        lambda handle, fmt, stream, fragment: real_call(handle, fmt, stream, bogus))
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        with pytest.raises(C2paError, match="UntrackedPointer") as caught:
            reader.with_fragment("video/mp4", init, fragment)
    assert f"0x{_addr(bogus):x}" in str(caught.value)
    _assert_closed(reader)
    assert consumed not in frees, "consumed handle must not be freed again"
    assert not _still_tracked(consumed), "native already dropped the reader"


def test_rejected_stream_after_context_reader_consumed_is_not_freed(
        monkeypatch, frees):
    bogus, _keep = _untracked_stream()
    real_call = binding._lib.c2pa_reader_with_stream
    seen = []

    def call(handle, fmt, stream):
        seen.append(_addr(handle))
        return real_call(handle, fmt, bogus)

    monkeypatch.setattr(binding._lib, "c2pa_reader_with_stream", call)
    with Context() as context, open(FIXTURES / "dashinit.mp4", "rb") as init:
        with pytest.raises(C2paError, match="UntrackedPointer"):
            Reader("video/mp4", init, context=context)
    assert len(seen) == 1, "the consume-first native call was not reached"
    assert seen[0] not in frees, "consumed reader must not be freed again"
    assert not _still_tracked(seen[0])


def test_rejection_naming_the_managed_handle_retains_it(reader):
    stale_owner, _keep = _untracked_stream()
    real_handle = reader._handle
    reader._handle = ctypes.cast(stale_owner, ctypes.POINTER(binding.C2paReader))
    try:
        with open(FIXTURES / "dashinit.mp4", "rb") as init, \
                open(FIXTURES / "dash1.m4s", "rb") as fragment:
            with pytest.raises(C2paError, match="UntrackedPointer"):
                reader.with_fragment("video/mp4", init, fragment)
        assert reader._lifecycle_state == LifecycleState.ACTIVE
    finally:
        reader._handle = real_handle
    assert reader.json()


def test_successful_fragment_swap_replaces_without_freeing_consumed(reader, frees):
    consumed = reader._handle_value()
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        reader.with_fragment("video/mp4", init, fragment)
    assert reader._handle_value() not in (None, consumed)
    assert consumed not in frees
    assert not _still_tracked(consumed)
    replacement = reader._handle_value()
    reader.close()
    reader.close()
    assert frees.count(replacement) == 1


@pytest.mark.parametrize("tag", [
    "Other: PointerInUse: handle already in (exclusive) use",
    "Other: WrongWrapperKind: Arc-backed handle can't have single ownership",
])
def test_addressless_rejection_on_consume_first_call_releases_defensively(
        reader, monkeypatch, frees, tag):
    managed = reader._handle_value()

    def rejected(*_args):
        binding._lib.c2pa_error_set_last(tag.encode())
        return None

    monkeypatch.setattr(binding._lib, "c2pa_reader_with_fragment", rejected)
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        with pytest.raises(C2paError) as caught:
            reader.with_fragment("video/mp4", init, fragment)
    # The original rejection survives the defensive free's own error slot.
    assert tag.split(": ", 1)[1].split(":")[0] in str(caught.value)
    assert frees.count(managed) == 1
    _assert_closed(reader)
    assert frees.count(managed) == 1
    assert not _still_tracked(managed)


def test_invalid_archive_stream_after_builder_consumed_closes_builder(
        monkeypatch, frees):
    builder = Builder({"claim_generator_info": [{"name": "ownership-test"}],
                       "assertions": []})
    consumed = builder._handle_value()
    bogus, _keep = _untracked_stream()
    real_call = binding._lib.c2pa_builder_with_archive
    monkeypatch.setattr(binding._lib, "c2pa_builder_with_archive",
                        lambda handle, stream: real_call(handle, bogus))
    with pytest.raises(C2paError, match="UntrackedPointer"):
        builder.with_archive(io.BytesIO(b"unused"))
    _assert_closed(builder)
    assert consumed not in frees
    assert not _still_tracked(consumed)


def _signer():
    return Signer.from_info(C2paSignerInfo(
        alg=b"es256", sign_cert=(FIXTURES / "es256_certs.pem").read_bytes(),
        private_key=(FIXTURES / "es256_private.key").read_bytes(), ta_url=None))


@pytest.mark.parametrize("tag", [
    "Other: PointerInUse: handle already in (exclusive) use",
    "Other: UntrackedPointer: 0x3",
])
def test_set_signer_validates_builder_first_so_rejection_retains_signer(
        monkeypatch, tag):
    signer = _signer()

    def rejected(*_args):
        binding._lib.c2pa_error_set_last(tag.encode())
        return -1

    monkeypatch.setattr(binding._lib, "c2pa_context_builder_set_signer", rejected)
    with pytest.raises(C2paError):
        Context(signer=signer)
    assert signer._lifecycle_state == LifecycleState.ACTIVE
    assert signer.reserve_size() > 0
    signer.close()
