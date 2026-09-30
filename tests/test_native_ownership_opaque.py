"""Opaque-registry-only ownership checks for the consolidated native.

On the paired opaque native (odd, never-reused object ids) a consumed handle
is provably gone from the registry, so these tests additionally assert that
no consumed id is still tracked. Stock natives reuse raw addresses, so this
cannot be asserted there; generic ownership tests live in
test_native_ownership.py.
"""

import ctypes
import io
from pathlib import Path

import pytest

import c2pa.c2pa as binding
from c2pa import Builder, C2paError, Context, Reader

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not binding.has_live_video_trusted_vsi_signing_context_v1(),
    reason="requires the paired opaque-registry native",
)


@pytest.fixture(autouse=True)
def _clear_native_error_slot():
    yield
    binding._lib.c2pa_error_set_last(b"Other: cleared by test teardown")


def _untracked_stream():
    buffer = ctypes.create_string_buffer(64)
    return ctypes.cast(buffer, ctypes.POINTER(binding.C2paStream)), buffer


def _still_tracked(handle_value):
    """Return whether the registry still tracks an id (frees it if so)."""
    return binding._lib.c2pa_free(ctypes.c_void_p(handle_value)) == 0


def test_consumed_reader_id_is_gone_after_rejected_fragment(monkeypatch):
    with open(FIXTURES / "dashinit.mp4", "rb") as init:
        reader = Reader("video/mp4", init)
    consumed = reader._handle_value()
    bogus, _keep = _untracked_stream()
    real_call = binding._lib.c2pa_reader_with_fragment
    monkeypatch.setattr(
        binding._lib, "c2pa_reader_with_fragment",
        lambda handle, fmt, stream, fragment: real_call(handle, fmt, stream, bogus))
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        with pytest.raises(C2paError, match="UntrackedPointer"):
            reader.with_fragment("video/mp4", init, fragment)
    assert not _still_tracked(consumed)


def test_consumed_context_reader_id_is_gone_after_rejected_stream(monkeypatch):
    bogus, _keep = _untracked_stream()
    real_call = binding._lib.c2pa_reader_with_stream
    seen = []

    def call(handle, fmt, stream):
        seen.append(ctypes.cast(handle, ctypes.c_void_p).value)
        return real_call(handle, fmt, bogus)

    monkeypatch.setattr(binding._lib, "c2pa_reader_with_stream", call)
    with Context() as context, open(FIXTURES / "dashinit.mp4", "rb") as init:
        with pytest.raises(C2paError, match="UntrackedPointer"):
            Reader("video/mp4", init, context=context)
    assert len(seen) == 1 and not _still_tracked(seen[0])


def test_consumed_builder_id_is_gone_after_rejected_archive(monkeypatch):
    builder = Builder({"claim_generator_info": [{"name": "ownership-test"}],
                       "assertions": []})
    consumed = builder._handle_value()
    bogus, _keep = _untracked_stream()
    real_call = binding._lib.c2pa_builder_with_archive
    monkeypatch.setattr(binding._lib, "c2pa_builder_with_archive",
                        lambda handle, stream: real_call(handle, bogus))
    with pytest.raises(C2paError, match="UntrackedPointer"):
        builder.with_archive(io.BytesIO(b"unused"))
    assert not _still_tracked(consumed)


def test_successful_swap_leaves_consumed_id_untracked():
    with open(FIXTURES / "dashinit.mp4", "rb") as init:
        reader = Reader("video/mp4", init)
    consumed = reader._handle_value()
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        reader.with_fragment("video/mp4", init, fragment)
    assert not _still_tracked(consumed)
    reader.close()
