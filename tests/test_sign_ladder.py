"""Focused binding tests and an optional-capability, offline native smoke."""

import ctypes
import gc
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import c2pa.c2pa as binding


_NATIVE_SIGNATURE = ctypes.CFUNCTYPE(
    ctypes.c_int64,
    ctypes.POINTER(binding.C2paBuilder),
    ctypes.POINTER(binding.C2paSigner),
    ctypes.POINTER(ctypes.c_char_p),
    ctypes.POINTER(ctypes.c_char_p),
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
)


@pytest.fixture
def ladder(monkeypatch):
    # Mock retains call arguments; gc.collect() below is not a lifetime proof.
    native = SimpleNamespace(
        c2pa_builder_sign_ladder=Mock(),
        c2pa_free=Mock(return_value=0),
    )
    monkeypatch.setattr(binding, "_lib", native)
    monkeypatch.setattr(binding, "_HAS_SIGN_LADDER", True)
    builder = binding.Builder._wrap_native_handle(
        ctypes.pointer(binding.C2paBuilder()))
    signer = binding.Signer._wrap_native_handle(
        ctypes.pointer(binding.C2paSigner()))
    yield builder, signer, native
    builder.close()
    signer.close()


def manifest_result(native, result=4, error=None):
    buffer = (ctypes.c_ubyte * 4)(65, 0, 66, 255)

    def sign(*args):
        output = ctypes.cast(
            args[-1], ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)))
        output[0] = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        if error:
            raise error
        return result

    native.c2pa_builder_sign_ladder.side_effect = sign
    return buffer


def assert_closed(builder, signer, native, manifest=None):
    assert builder._lifecycle_state == binding.LifecycleState.CLOSED
    assert builder._handle is None
    signer._ensure_valid_state()
    builder_handle = native.c2pa_builder_sign_ladder.call_args.args[0]
    expected = [ctypes.addressof(manifest)] if manifest is not None else []
    expected.append(ctypes.addressof(builder_handle.contents))
    calls = native.c2pa_free.call_args_list[:]
    assert [ctypes.addressof(call.args[0].contents) for call in calls] == expected
    builder.close()
    assert native.c2pa_free.call_args_list == calls
    with pytest.raises(binding.C2paError, match="closed"):
        builder.sign_ladder(signer, ["in.mp4"], ["out.mp4"])
    native.c2pa_builder_sign_ladder.assert_called_once()
    assert native.c2pa_free.call_args_list == calls


def test_order_utf8_marshalling_and_binary_copy(ladder):
    builder, signer, native = ladder
    manifest = manifest_result(native)
    sign = native.c2pa_builder_sign_ladder.side_effect
    builder_handle = builder._handle
    signer_handle = signer._handle

    def inspect(*args):
        gc.collect()
        assert args[0] is builder_handle
        assert args[1] is signer_handle
        assert list(args[2]) == [b"z.mp4", "\u00e9.mp4".encode()]
        assert list(args[3]) == [b"out-z.mp4", b"out-e.mp4"]
        assert args[4] == 2
        return sign(*args)

    native.c2pa_builder_sign_ladder.side_effect = inspect
    assert builder.sign_ladder(
        signer, [Path("z.mp4"), "\u00e9.mp4"],
        ["out-z.mp4", Path("out-e.mp4")]) == b"A\0B\xff"
    assert_closed(builder, signer, native, manifest)


@pytest.mark.parametrize("result", [4, -1])
def test_typed_callback_marshalling_and_cleanup(ladder, monkeypatch, result):
    builder, signer, native = ladder
    manifest = (ctypes.c_ubyte * 4)(65, 0, 66, 255)
    calls = []

    @_NATIVE_SIGNATURE
    def sign(builder_ptr, signer_ptr, sources, dests, count, output):
        gc.collect()
        calls.append((ctypes.addressof(builder_ptr.contents),
                      ctypes.addressof(signer_ptr.contents),
                      [sources[i] for i in range(count)],
                      [dests[i] for i in range(count)], count))
        output[0] = ctypes.cast(manifest, ctypes.POINTER(ctypes.c_ubyte))
        return result

    native.c2pa_builder_sign_ladder.side_effect = sign
    expected = (ctypes.addressof(builder._handle.contents),
                ctypes.addressof(signer._handle.contents),
                [b"z.mp4", "\u00e9.mp4".encode()],
                [b"out-z.mp4", "out-\u00e9.mp4".encode()], 2)
    sources = [Path("z.mp4"), "\u00e9.mp4"]
    dests = ["out-z.mp4", Path("out-\u00e9.mp4")]
    if result < 0:
        monkeypatch.setattr(binding, "_read_native_error", lambda: "Io: sign failed")
        with pytest.raises(binding.C2paError.Io, match="sign failed"):
            builder.sign_ladder(signer, sources, dests)
    else:
        assert builder.sign_ladder(signer, sources, dests) == b"A\0B\xff"
    # Assert outside the ctypes callback, which would swallow assertion errors.
    assert calls == [expected]
    assert_closed(builder, signer, native, manifest)


@pytest.mark.parametrize("sources,dests,error", [
    ([], [], binding.C2paError),
    (["a"] * 257, ["b"] * 257, binding.C2paError),
    (["a"], [], binding.C2paError),
    ("a", ["b"], binding.C2paError),
    (["a"], "b", binding.C2paError),
    (["a\0hidden"], ["b"], binding.C2paError.Encoding),
    (["a"], [Path("b\0hidden")], binding.C2paError.Encoding),
    (["\ud800"], ["b"], binding.C2paError.Encoding),
    (["a"], ["\udfff"], binding.C2paError.Encoding),
    ([b"a"], ["b"], binding.C2paError.Encoding),
    ([object()], ["b"], binding.C2paError.Encoding),
])
def test_path_preflight_preserves_builder(ladder, sources, dests, error):
    builder, signer, native = ladder
    with pytest.raises(error):
        builder.sign_ladder(signer, sources, dests)
    native.c2pa_builder_sign_ladder.assert_not_called()
    native.c2pa_free.assert_not_called()
    builder._ensure_valid_state()
    manifest_result(native)
    assert builder.sign_ladder(signer, ["a"], ["b"]) == b"A\0B\xff"


@pytest.mark.parametrize("kind", ["none", "object", "duck", "closed", "uninitialized"])
def test_requires_active_explicit_signer(ladder, kind):
    builder, signer, native = ladder
    builder._has_context_signer = True
    invalid = {"none": None, "object": object(),
               "duck": SimpleNamespace(_handle=signer._handle)}
    if kind == "closed":
        signer.close()
        invalid[kind] = signer
    if kind == "uninitialized":
        invalid[kind] = binding.Signer.__new__(binding.Signer)
        binding.ManagedResource.__init__(invalid[kind])
        invalid[kind]._init_attrs()
    with pytest.raises(binding.C2paError):
        builder.sign_ladder(invalid[kind], ["a"], ["b"])
    native.c2pa_builder_sign_ladder.assert_not_called()
    builder._ensure_valid_state()


def test_capability_preflight_preserves_builder(ladder, monkeypatch):
    builder, signer, native = ladder
    monkeypatch.setattr(binding, "_HAS_SIGN_LADDER", False)
    with pytest.raises(binding.C2paError.NotSupported,
                       match="c2pa_builder_sign_ladder"):
        builder.sign_ladder(signer, ["a"], ["b"])
    native.c2pa_builder_sign_ladder.assert_not_called()
    native.c2pa_free.assert_not_called()
    builder._ensure_valid_state()


@pytest.mark.parametrize("allocated", [False, True])
def test_native_typed_error_and_cleanup(ladder, monkeypatch, allocated):
    builder, signer, native = ladder
    monkeypatch.setattr(binding, "_read_native_error",
                        lambda: "Io: cannot write destination")
    manifest = None
    if allocated:
        manifest = manifest_result(native, result=-1)
    else:
        native.c2pa_builder_sign_ladder.return_value = -1
    with pytest.raises(binding.C2paError.Io, match="cannot write"):
        builder.sign_ladder(signer, ["a"], ["b"])
    assert_closed(builder, signer, native, manifest)


@pytest.mark.parametrize("allocated", [False, True])
def test_call_exception_and_cleanup(ladder, allocated):
    builder, signer, native = ladder
    error = ctypes.ArgumentError("call failed")
    manifest = None
    if allocated:
        manifest = manifest_result(native, error=error)
    else:
        native.c2pa_builder_sign_ladder.side_effect = error
    with pytest.raises(binding.C2paError, match="call failed") as caught:
        builder.sign_ladder(signer, ["a"], ["b"])
    assert caught.value.__cause__ is error
    assert_closed(builder, signer, native, manifest)


def test_copy_error_is_not_success(ladder, monkeypatch):
    builder, signer, native = ladder
    manifest = manifest_result(native)
    error = MemoryError("copy failed")
    # ctypes is shared process-wide; limit the patch to this mocked call.
    with monkeypatch.context() as patch:
        patch.setattr(binding.ctypes, "string_at", Mock(side_effect=error))
        with pytest.raises(binding.C2paError, match="copy failed") as caught:
            builder.sign_ladder(signer, ["a"], ["b"])
    assert caught.value.__cause__ is error
    assert_closed(builder, signer, native, manifest)


@pytest.mark.parametrize("result,allocated", [(0, False), (0, True), (4, False)])
def test_missing_manifest_is_not_success(ladder, result, allocated):
    builder, signer, native = ladder
    manifest = None
    if allocated:
        manifest = manifest_result(native, result=result)
    else:
        native.c2pa_builder_sign_ladder.return_value = result
    with pytest.raises(binding.C2paError, match="no manifest bytes"):
        builder.sign_ladder(signer, ["a"], ["b"])
    assert_closed(builder, signer, native, manifest)


@pytest.mark.parametrize("result", [4, -1])
def test_free_error_still_closes_builder(ladder, caplog, monkeypatch, result):
    builder, signer, native = ladder
    manifest = manifest_result(native, result=result)

    def free(pointer):
        if ctypes.addressof(pointer.contents) == ctypes.addressof(manifest):
            raise RuntimeError("free failed")
        return 0

    native.c2pa_free.side_effect = free
    if result < 0:
        monkeypatch.setattr(binding, "_read_native_error", lambda: "Io: sign failed")
        with pytest.raises(binding.C2paError.Io, match="sign failed"):
            builder.sign_ladder(signer, ["a"], ["b"])
    else:
        assert builder.sign_ladder(signer, ["a"], ["b"]) == b"A\0B\xff"
    assert "Failed to release native manifest bytes memory" in caplog.text
    assert_closed(builder, signer, native, manifest)


@pytest.mark.parametrize("mode", ["-O", "-OO", "PYTHONOPTIMIZE"])
def test_native_harness_refuses_optimized_python(mode):
    env = os.environ.copy()
    env.pop("PYTHONOPTIMIZE", None)
    command = [sys.executable]
    if mode == "PYTHONOPTIMIZE":
        env[mode] = "1"
    else:
        command.append(mode)
    command.append(str(Path(__file__).with_name("ladder_native.py")))
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "requires assertions" in result.stderr
    assert "rerun without -O/-OO or PYTHONOPTIMIZE" in result.stderr


def test_real_native_ladder_signs_and_validates(tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    fixture = fixtures / "single-file-fragmented" / "single_file_fragments.mp4"
    original = fixture.read_bytes()  # Missing committed test data is never a skip.
    if not binding._HAS_SIGN_LADDER:
        if os.environ.get("C2PA_REQUIRE_SIGN_LADDER") == "1":
            pytest.fail("C2PA_REQUIRE_SIGN_LADDER=1 but the loaded native library "
                        "lacks c2pa_builder_sign_ladder")
        pytest.skip("native library lacks c2pa_builder_sign_ladder")

    export = binding._lib.c2pa_builder_sign_ladder
    assert export.restype is _NATIVE_SIGNATURE._restype_
    assert tuple(export.argtypes) == _NATIVE_SIGNATURE._argtypes_

    # Two copies exercise the ordered multi-file API, not different encodes.
    sources = [tmp_path / f"copy-{i}.mp4" for i in range(2)]
    dests = [tmp_path / f"signed-{i}.mp4" for i in range(2)]
    for source in sources:
        shutil.copy2(fixture, source)
    definition = {
        "claim_generator_info": [{"name": "ladder-binding-test"}],
        "assertions": [{"label": "c2pa.actions", "data": {"actions": [{
            "action": "c2pa.created",
            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
        }]}}],
    }
    info = binding.C2paSignerInfo(
        alg=b"es256", sign_cert=(fixtures / "es256_certs.pem").read_bytes(),
        private_key=(fixtures / "es256_private.key").read_bytes(), ta_url=None)
    with binding.Signer.from_info(info) as signer:
        with binding.Builder(definition) as builder:
            with pytest.raises(binding.C2paError, match="1 to 256"):
                builder.sign_ladder(signer, [], [])
            builder._ensure_valid_state()
            manifest = builder.sign_ladder(signer, sources, dests)
            assert manifest
            assert builder._lifecycle_state == binding.LifecycleState.CLOSED
            assert builder._handle is None
        signer._ensure_valid_state()

    manifests = []
    for dest in dests:
        assert manifest in dest.read_bytes(), "returned manifest not embedded byte-for-byte"
        with binding.Reader(dest) as reader:
            assert reader.get_validation_state() == "Valid", reader.json()
            report = json.loads(reader.json())
            manifests.append(report["manifests"][report["active_manifest"]])
    assert manifests[0] == manifests[1]
    assert [source.read_bytes() for source in sources] == [original, original]
    assert fixture.read_bytes() == original
