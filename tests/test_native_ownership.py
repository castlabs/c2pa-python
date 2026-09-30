"""Native ownership regressions for raw-address and opaque-handle registries.

Consume-first calls can reject another argument after dropping their managed
handle. Never probe a consumed address with c2pa_free: on the raw-address
registry it may already belong to a new allocation.
"""

import ctypes
import io
from pathlib import Path

import pytest

import c2pa.c2pa as binding
from c2pa import Builder, C2paError, C2paSignerInfo, Context, Reader, Signer
from c2pa.c2pa import LifecycleState, ManagedResource


FIXTURES = Path(__file__).parent / "fixtures"


def _addr(pointer):
    return ctypes.cast(pointer, ctypes.c_void_p).value


def _untracked_pointer(pointer_type):
    # Keep the buffer alive so its address cannot become a native allocation.
    buffer = ctypes.create_string_buffer(64)
    return ctypes.cast(buffer, ctypes.POINTER(pointer_type)), buffer


@pytest.fixture(autouse=True)
def _restore_native_error_slot():
    # The slot is sticky and thread-local. Neutral text works on both libraries.
    binding._lib.c2pa_error_set_last(b"Other: native ownership test setup")
    yield
    binding._lib.c2pa_error_set_last(b"Other: native ownership test teardown")


@pytest.fixture
def reader():
    with open(FIXTURES / "dashinit.mp4", "rb") as init:
        value = Reader("video/mp4", init)
    try:
        yield value
    finally:
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


def test_rejected_fragment_stream_after_reader_consumed_closes_reader(
        reader, monkeypatch, frees):
    consumed = _addr(reader._handle)
    bogus, _keep = _untracked_pointer(binding.C2paStream)
    real_call = binding._lib.c2pa_reader_with_fragment
    monkeypatch.setattr(
        binding._lib, "c2pa_reader_with_fragment",
        lambda handle, fmt, stream, fragment: real_call(handle, fmt, stream, bogus))
    before = len(frees)
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        with pytest.raises(C2paError, match="UntrackedPointer") as caught:
            reader.with_fragment("video/mp4", init, fragment)
    assert f"0x{_addr(bogus):x}" in str(caught.value)
    _assert_closed(reader)
    assert consumed not in frees[before:]


def test_rejected_stream_after_context_reader_consumed_is_not_freed(
        monkeypatch, frees):
    bogus, _keep = _untracked_pointer(binding.C2paStream)
    real_call = binding._lib.c2pa_reader_with_stream
    seen = []

    def call(handle, fmt, stream):
        seen.append((_addr(handle), len(frees)))
        return real_call(handle, fmt, bogus)

    monkeypatch.setattr(binding._lib, "c2pa_reader_with_stream", call)
    with Context() as context, open(FIXTURES / "dashinit.mp4", "rb") as init:
        partial_reader = Reader.__new__(Reader)
        with pytest.raises(C2paError, match="UntrackedPointer"):
            partial_reader.__init__("video/mp4", init, context=context)
        assert len(seen) == 1, "the consume-first native call was not reached"
        consumed, before = seen[0]
        _assert_closed(partial_reader)
        # Check before context cleanup or any later allocation can reuse it.
        assert consumed not in frees[before:]


def test_rejection_naming_the_managed_handle_retains_it(reader, frees):
    bogus, _keep = _untracked_pointer(binding.C2paReader)
    real_handle = reader._handle
    reader._handle = bogus
    before = len(frees)
    try:
        with open(FIXTURES / "dashinit.mp4", "rb") as init, \
                open(FIXTURES / "dash1.m4s", "rb") as fragment:
            with pytest.raises(C2paError, match="UntrackedPointer") as caught:
                reader.with_fragment("video/mp4", init, fragment)
        assert f"0x{_addr(bogus):x}" in str(caught.value)
        assert reader._handle is bogus
        assert reader._lifecycle_state == LifecycleState.ACTIVE
        assert _addr(bogus) not in frees[before:]
    finally:
        reader._handle = real_handle
    assert reader.json()


def test_successful_fragment_swap_does_not_free_old_and_closes_replacement_once(
        reader, frees):
    consumed = _addr(reader._handle)
    before = len(frees)
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        assert reader.with_fragment("video/mp4", init, fragment) is reader
    assert reader._lifecycle_state == LifecycleState.ACTIVE
    assert reader._handle
    assert consumed not in frees[before:], "swap must not free the consumed handle"
    replacement = _addr(reader._handle)
    # The replacement may have the same address as the consumed reader.
    before_close = len(frees)
    reader.close()
    _assert_closed(reader)
    assert frees[before_close:] == [replacement]


@pytest.mark.parametrize("tag", [
    "Other: PointerInUse: handle already in (exclusive) use",
    "Other: WrongWrapperKind: Arc-backed handle can't have single ownership",
])
def test_addressless_rejection_on_consume_first_call_releases_defensively(
        reader, monkeypatch, frees, tag):
    managed = _addr(reader._handle)

    def rejected(*_args):
        # Stock does not emit these tags, but can hold them in its error slot.
        binding._lib.c2pa_error_set_last(tag.encode())
        return None

    monkeypatch.setattr(binding._lib, "c2pa_reader_with_fragment", rejected)
    before = len(frees)
    with open(FIXTURES / "dashinit.mp4", "rb") as init, \
            open(FIXTURES / "dash1.m4s", "rb") as fragment:
        with pytest.raises(C2paError) as caught:
            reader.with_fragment("video/mp4", init, fragment)
    assert tag.split(": ", 1)[1].split(":")[0] in str(caught.value)
    _assert_closed(reader)
    assert frees[before:] == [managed]


def test_rejected_archive_stream_after_builder_consumed_closes_without_free(
        monkeypatch, frees):
    builder = Builder({"claim_generator_info": [{"name": "ownership-test"}],
                       "assertions": []})
    consumed = _addr(builder._handle)
    bogus, _keep = _untracked_pointer(binding.C2paStream)
    real_call = binding._lib.c2pa_builder_with_archive
    monkeypatch.setattr(binding._lib, "c2pa_builder_with_archive",
                        lambda handle, stream: real_call(handle, bogus))
    before = len(frees)
    try:
        with pytest.raises(C2paError, match="UntrackedPointer"):
            builder.with_archive(io.BytesIO(b"unused"))
        _assert_closed(builder)
        assert consumed not in frees[before:]
    finally:
        builder.close()


def test_set_signer_validates_builder_first_and_retains_signer(monkeypatch, frees):
    signer = Signer.from_info(C2paSignerInfo(
        alg=b"es256", sign_cert=(FIXTURES / "es256_certs.pem").read_bytes(),
        private_key=(FIXTURES / "es256_private.key").read_bytes(), ta_url=None))
    bogus, _keep = _untracked_pointer(binding.C2paContextBuilder)
    # Do not allocate a real native builder that a failing constructor could leak.
    monkeypatch.setattr(binding._lib, "c2pa_context_builder_new", lambda: bogus)
    managed = _addr(signer._handle)
    before = len(frees)
    try:
        with pytest.raises(C2paError, match="UntrackedPointer") as caught:
            Context(signer=signer)
        assert f"0x{_addr(bogus):x}" in str(caught.value)
        assert signer._lifecycle_state == LifecycleState.ACTIVE
        assert _addr(signer._handle) == managed
        assert managed not in frees[before:]
        assert signer.reserve_size() > 0
    finally:
        signer.close()


@pytest.mark.parametrize("tag", [
    "UntrackedPointer", "WrongPointerType", "PointerInUse", "WrongWrapperKind",
])
def test_invalid_definition_quoting_registry_tag_does_not_free_consumed_builder(
        monkeypatch, frees, tag):
    real_call = binding._lib.c2pa_builder_with_definition
    seen = []

    def call(handle, definition):
        seen.append((_addr(handle), len(frees)))
        return real_call(handle, definition)

    monkeypatch.setattr(binding._lib, "c2pa_builder_with_definition", call)
    with Context() as context:
        builder = Builder.__new__(Builder)
        with pytest.raises(C2paError, match="Json") as caught:
            builder.__init__({"claim_version": f"{tag}: 0xcafe"}, context=context)
        assert tag in str(caught.value)
        assert len(seen) == 1
        consumed, before = seen[0]
        _assert_closed(builder)
        assert consumed not in frees[before:]
