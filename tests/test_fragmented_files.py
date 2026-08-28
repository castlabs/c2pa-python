"""Focused coverage for fragmented BMFF file-set Python APIs."""

from __future__ import annotations

import ctypes
import gc
import json
import tempfile
import unittest
import weakref
from pathlib import Path

from c2pa import (
    Builder,
    C2paError,
    C2paSignerInfo,
    C2paSigningAlg,
    Context,
    Reader,
    Settings,
    Signer,
    has_dynamic_assertions,
    has_fragmented_files,
)
from c2pa.c2pa import LifecycleState, ManagedResource
import c2pa.c2pa as c2pa_module


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _manifest_definition() -> dict:
    return {
        "claim_generator": "python_test_sign_fragmented",
        "claim_generator_info": [{
            "name": "python_test_sign_fragmented",
            "version": "0.0.1",
        }],
        "claim_version": 1,
        "format": "video/mp4",
        "title": "python fragmented file-set test",
        "assertions": [{
            "label": "c2pa.actions.v2",
            "data": {
                "actions": [{"action": "c2pa.watermarked.bound"}],
            },
        }],
    }


def _unsigned_init_segment(segment: bytes) -> bytes:
    """Keep only ftyp/moov from the existing signed DASH init fixture."""
    kept = []
    offset = 0
    while offset < len(segment):
        if len(segment) - offset < 8:
            raise AssertionError("truncated top-level BMFF box")
        size = int.from_bytes(segment[offset:offset + 4], "big")
        box_type = segment[offset + 4:offset + 8]
        header_size = 8
        if size == 1:
            if len(segment) - offset < 16:
                raise AssertionError("truncated extended BMFF box")
            size = int.from_bytes(segment[offset + 8:offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = len(segment) - offset
        if size < header_size or offset + size > len(segment):
            raise AssertionError("invalid top-level BMFF box size")
        if box_type in (b"ftyp", b"moov"):
            kept.append(segment[offset:offset + size])
        offset += size
    if len(kept) != 2:
        raise AssertionError("expected ftyp and moov in DASH init fixture")
    return b"".join(kept)


def _unsigned_fragment(segment: bytes) -> bytes:
    """Remove the top-level C2PA Merkle-map UUID from the signed fixture."""
    kept = []
    offset = 0
    while offset < len(segment):
        if len(segment) - offset < 8:
            raise AssertionError("truncated top-level BMFF box")
        size = int.from_bytes(segment[offset:offset + 4], "big")
        box_type = segment[offset + 4:offset + 8]
        header_size = 8
        if size == 1:
            if len(segment) - offset < 16:
                raise AssertionError("truncated extended BMFF box")
            size = int.from_bytes(segment[offset + 8:offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = len(segment) - offset
        if size < header_size or offset + size > len(segment):
            raise AssertionError("invalid top-level BMFF box size")
        if box_type != b"uuid":
            kept.append(segment[offset:offset + size])
        offset += size
    return b"".join(kept)


class FragmentedTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURES_DIR / "es256_certs.pem", "rb") as file:
            cls.certs = file.read()
        with open(FIXTURES_DIR / "es256_private.key", "rb") as file:
            cls.key = file.read()

    def _make_signer(self) -> Signer:
        return Signer.from_info(C2paSignerInfo(
            alg=b"es256",
            sign_cert=self.certs,
            private_key=self.key,
            ta_url=None,
        ))

    def _make_callback_signer(self) -> Signer:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric import utils

        key = serialization.load_pem_private_key(
            self.key, password=None, backend=default_backend())

        def callback(data: bytes) -> bytes:
            der = key.sign(data, ec.ECDSA(hashes.SHA256()))
            r, s = utils.decode_dss_signature(der)
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")

        return Signer.from_callback(
            callback,
            C2paSigningAlg.ES256,
            self.certs.decode("utf-8"),
            None,
        )

    def _prepare_input(self, root: Path) -> tuple[Path, Path]:
        input_dir = root / "input"
        input_dir.mkdir()
        init_path = input_dir / "init.mp4"
        with open(FIXTURES_DIR / "dashinit.mp4", "rb") as file:
            init_path.write_bytes(_unsigned_init_segment(file.read()))
        fragment_path = input_dir / "segment-0001.m4s"
        with open(FIXTURES_DIR / "dash1.m4s", "rb") as file:
            fragment_path.write_bytes(_unsigned_fragment(file.read()))
        return init_path, fragment_path

    def _sign(
        self,
        root: Path,
        signer: Signer,
        context: Context | None = None,
    ) -> tuple[bytes, Path, list[Path], Builder]:
        init_path, _ = self._prepare_input(root)
        output_dir = root / "output"
        builder = Builder(_manifest_definition(), context=context)
        manifest = builder.sign_fragmented(
            signer,
            init_path,
            "segment-*.m4s",
            output_dir,
        )
        signed_dir = output_dir / "input"
        return (
            manifest,
            signed_dir / init_path.name,
            sorted(signed_dir.glob("segment-*.m4s")),
            builder,
        )


class TestFragmentedCapability(FragmentedTestCase):
    def test_standard_export_validation_does_not_require_fragmented_files(self):
        fragmented_symbols = (
            c2pa_module._FRAGMENTED_SIGN_FUNCTIONS
            + c2pa_module._FRAGMENTED_READER_FUNCTIONS
            + c2pa_module._FRAGMENTED_CONTEXT_READER_FUNCTIONS
        )

        class StandardLibrary:
            def __getattr__(self, name):
                if name in fragmented_symbols:
                    raise AttributeError(name)
                return getattr(c2pa_module._lib, name)

        c2pa_module._validate_library_exports(StandardLibrary())

    def test_missing_capability_has_clear_errors(self):
        signer = self._make_signer()
        builder = Builder(_manifest_definition())
        context = Context()
        available = (
            c2pa_module._FRAGMENTED_SIGN_AVAILABLE,
            c2pa_module._FRAGMENTED_READER_AVAILABLE,
            c2pa_module._FRAGMENTED_CONTEXT_READER_AVAILABLE,
        )
        try:
            c2pa_module._FRAGMENTED_SIGN_AVAILABLE = False
            self.assertFalse(has_fragmented_files())
            with self.assertRaises(C2paError.NotSupported):
                builder.sign_fragmented(
                    signer, "unused.mp4", "*.m4s", "output")
            self.assertTrue(builder.is_valid)
            self.assertTrue(signer.is_valid)

            c2pa_module._FRAGMENTED_READER_AVAILABLE = False
            with self.assertRaises(C2paError.NotSupported):
                Reader.from_fragmented_files("init.mp4", ["segment.m4s"])

            c2pa_module._FRAGMENTED_CONTEXT_READER_AVAILABLE = False
            with self.assertRaises(C2paError.NotSupported):
                Reader.from_fragmented_files(
                    "init.mp4", ["segment.m4s"], context=context)
        finally:
            (
                c2pa_module._FRAGMENTED_SIGN_AVAILABLE,
                c2pa_module._FRAGMENTED_READER_AVAILABLE,
                c2pa_module._FRAGMENTED_CONTEXT_READER_AVAILABLE,
            ) = available
            builder.close()
            signer.close()
            context.close()


@unittest.skipUnless(
    has_fragmented_files(),
    "native library does not provide fragmented BMFF file APIs",
)
class TestFragmentedFiles(FragmentedTestCase):
    def test_successful_sign_and_legacy_read_round_trip(self):
        signer = self._make_signer()
        self.addCleanup(signer.close)
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest, signed_init, fragments, builder = self._sign(
                Path(temp_dir), signer)

            self.assertIsInstance(manifest, bytes)
            self.assertGreater(len(manifest), 0)
            self.assertIn(b"c2pa", manifest)
            self.assertTrue(signed_init.is_file())
            self.assertEqual(len(fragments), 1)
            self.assertFalse(builder.is_valid)
            self.assertTrue(signer.is_valid)

            with Reader.from_fragmented_files(
                signed_init, fragments,
            ) as reader:
                report = json.loads(reader.json())
                active = report["manifests"][report["active_manifest"]]
                self.assertEqual(
                    active["title"], "python fragmented file-set test")

    def test_callback_signer_remains_active_and_owned_by_caller(self):
        signer = self._make_callback_signer()
        callback_ref = weakref.ref(signer._callback_cb)
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest, _, _, builder = self._sign(Path(temp_dir), signer)

        self.assertGreater(len(manifest), 0)
        self.assertFalse(builder.is_valid)
        self.assertTrue(signer.is_valid)
        self.assertIsNotNone(callback_ref())
        signer.close()
        del signer
        gc.collect()
        self.assertIsNone(callback_ref())

    def test_explicit_context_applies_trust_and_pins_callbacks(self):
        with open(
            Path(__file__).parent / "trust_config_test_settings.json",
            "r",
            encoding="utf-8",
        ) as file:
            settings = Settings.from_dict(json.load(file))
        context_signer = self._make_callback_signer()
        context = Context(settings=settings, signer=context_signer)
        settings.close()
        explicit_signer = self._make_signer()
        self.addCleanup(explicit_signer.close)

        with tempfile.TemporaryDirectory() as temp_dir:
            _, signed_init, fragments, _ = self._sign(
                Path(temp_dir), explicit_signer, context=context)

            legacy_call = c2pa_module._lib.c2pa_reader_from_fragmented_files
            context_call = (
                c2pa_module._lib.c2pa_reader_from_fragmented_files_context)
            calls = []

            def tracked_context_call(*args):
                calls.append("context")
                return context_call(*args)

            def rejected_legacy_call(*args):
                calls.append("legacy")
                return legacy_call(*args)

            c2pa_module._lib.c2pa_reader_from_fragmented_files = (
                rejected_legacy_call)
            c2pa_module._lib.c2pa_reader_from_fragmented_files_context = (
                tracked_context_call)
            try:
                reader = Reader.from_fragmented_files(
                    signed_init, fragments, context=context)
            finally:
                c2pa_module._lib.c2pa_reader_from_fragmented_files = legacy_call
                c2pa_module._lib.c2pa_reader_from_fragmented_files_context = (
                    context_call)

            self.assertEqual(calls, ["context"])
            self.assertEqual(reader.get_validation_state(), "Trusted")
            self.assertIs(reader._context, context)
            self.assertIsNotNone(reader._signer_callback_cb)
            callback_ref = weakref.ref(reader._signer_callback_cb)
            context_ref = weakref.ref(context)

            context.close()
            del context
            gc.collect()
            self.assertIsNotNone(context_ref())
            self.assertIsNotNone(callback_ref())
            self.assertTrue(reader.json())

            reader.close()
            del reader
            gc.collect()
            self.assertIsNone(context_ref())
            self.assertIsNone(callback_ref())

    def test_invalid_inputs_are_rejected_before_native_calls(self):
        signer = self._make_signer()
        self.addCleanup(signer.close)
        builder = Builder(_manifest_definition())
        self.addCleanup(builder.close)

        with self.assertRaises(TypeError):
            builder.sign_fragmented(object(), "init.mp4", "*.m4s", "out")
        for value in (None, b"init.mp4", "", "bad\0path"):
            with self.subTest(asset_path=value):
                with self.assertRaises((TypeError, ValueError)):
                    builder.sign_fragmented(signer, value, "*.m4s", "out")
        with self.assertRaises(ValueError):
            builder.sign_fragmented(signer, "*.mp4", "*.m4s", "out")
        with self.assertRaises(ValueError):
            builder.sign_fragmented(
                signer, "missing-init.mp4", "*.m4s", "out")
        self.assertTrue(builder.is_valid)
        self.assertTrue(signer.is_valid)

        with self.assertRaises(ValueError):
            Reader.from_fragmented_files("", ["segment.m4s"])
        for fragments in ([], "segment.m4s", iter(["segment.m4s"])):
            with self.subTest(fragments=fragments):
                with self.assertRaises((TypeError, ValueError)):
                    Reader.from_fragmented_files("init.mp4", fragments)
        for fragment in (None, b"segment.m4s", "", "bad\0path"):
            with self.subTest(fragment=fragment):
                with self.assertRaises((TypeError, ValueError)):
                    Reader.from_fragmented_files("init.mp4", [fragment])
        with self.assertRaises(TypeError):
            Reader.from_fragmented_files(
                "init.mp4", ["segment.m4s"], context=object())

        closed_context = Context()
        closed_context.close()
        with self.assertRaises(C2paError):
            Reader.from_fragmented_files(
                "init.mp4", ["segment.m4s"], context=closed_context)

    def test_output_and_handles_are_freed_exactly_once(self):
        gc.collect()
        signer = self._make_signer()
        self.addCleanup(signer.close)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_path, _ = self._prepare_input(root)
            builder = Builder(_manifest_definition())
            builder_handle = builder._handle
            free_calls = []
            real_free = ManagedResource._free_native_ptr

            def tracked_free(pointer):
                address = ctypes.cast(pointer, ctypes.c_void_p).value
                free_calls.append(address)
                return real_free(pointer)

            ManagedResource._free_native_ptr = staticmethod(tracked_free)
            try:
                manifest = builder.sign_fragmented(
                    signer, init_path, "segment-*.m4s", root / "output")
            finally:
                ManagedResource._free_native_ptr = real_free

            builder_address = ctypes.cast(
                builder_handle, ctypes.c_void_p).value
            self.assertGreater(len(manifest), 0)
            self.assertEqual(free_calls.count(builder_address), 1)
            self.assertEqual(len(free_calls), 2)
            self.assertEqual(len(set(free_calls)), 2)
            builder.close()

            signed_dir = root / "output" / "input"
            reader = Reader.from_fragmented_files(
                signed_dir / "init.mp4",
                [signed_dir / "segment-0001.m4s"],
            )
            reader_handle = reader._handle
            reader_address = ctypes.cast(reader_handle, ctypes.c_void_p).value
            reader_frees = []

            def tracked_reader_free(pointer):
                reader_frees.append(
                    ctypes.cast(pointer, ctypes.c_void_p).value)
                return real_free(pointer)

            ManagedResource._free_native_ptr = staticmethod(tracked_reader_free)
            try:
                reader.close()
                reader.close()
            finally:
                ManagedResource._free_native_ptr = real_free
            self.assertEqual(reader_frees.count(reader_address), 1)

    @unittest.skipUnless(
        has_dynamic_assertions(),
        "native library does not provide dynamic assertions",
    )
    def test_callback_error_is_reset_and_original_exception_is_reraised(self):
        class CallbackFailure(RuntimeError):
            pass

        failure = CallbackFailure("fragmented dynamic assertion failed")
        signer = self._make_signer()
        self.addCleanup(signer.close)

        def callback(*_args):
            raise failure

        signer.add_dynamic_assertion(
            callback, label="com.example.fragmented", reserve_size=64)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_path, _ = self._prepare_input(root)
            builder = Builder(_manifest_definition())
            with self.assertRaises(CallbackFailure) as raised:
                builder.sign_fragmented(
                    signer, init_path, "segment-*.m4s", root / "output")

        self.assertIs(raised.exception, failure)
        self.assertEqual(builder._lifecycle_state, LifecycleState.CLOSED)
        self.assertTrue(signer.is_valid)

        # A later native failure that never enters the callback must not
        # re-raise stale callback state from the prior operation.
        stale = CallbackFailure("stale callback failure")
        error_state = signer._dynamic_assertion_cbs[0][1]
        error_state.exception = stale
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_path, _ = self._prepare_input(root)
            builder = Builder(_manifest_definition())
            real_call = c2pa_module._lib.c2pa_builder_sign_fragmented

            def failed_call(*args):
                output = ctypes.cast(
                    args[-1],
                    ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
                )
                self.assertFalse(output[0])
                c2pa_module._lib.c2pa_error_set_last(
                    b"Other: mocked fragmented signing failure")
                return -1

            c2pa_module._lib.c2pa_builder_sign_fragmented = failed_call
            try:
                with self.assertRaises(C2paError) as raised:
                    builder.sign_fragmented(
                        signer,
                        init_path,
                        "segment-*.m4s",
                        root / "output",
                    )
            finally:
                c2pa_module._lib.c2pa_builder_sign_fragmented = real_call

        self.assertIsNot(raised.exception, stale)
        self.assertIsNone(error_state.exception)
        self.assertFalse(builder.is_valid)
        self.assertTrue(signer.is_valid)

    def test_mocked_output_is_copied_and_freed_once(self):
        signer = self._make_signer()
        self.addCleanup(signer.close)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_path, _ = self._prepare_input(root)
            builder = Builder(_manifest_definition())
            builder_handle = builder._handle
            output_buffer = (ctypes.c_ubyte * 4)(1, 2, 3, 4)
            output_address = ctypes.addressof(output_buffer)
            real_call = c2pa_module._lib.c2pa_builder_sign_fragmented
            real_free = ManagedResource._free_native_ptr
            free_calls = []

            def fake_call(*args):
                output = ctypes.cast(
                    args[-1],
                    ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
                )
                self.assertFalse(output[0])
                output[0] = ctypes.cast(
                    output_buffer, ctypes.POINTER(ctypes.c_ubyte))
                return len(output_buffer)

            def record_free(pointer):
                free_calls.append(ctypes.cast(pointer, ctypes.c_void_p).value)
                return 0

            c2pa_module._lib.c2pa_builder_sign_fragmented = fake_call
            ManagedResource._free_native_ptr = staticmethod(record_free)
            try:
                result = builder.sign_fragmented(
                    signer, init_path, "segment-*.m4s", root / "output")
            finally:
                c2pa_module._lib.c2pa_builder_sign_fragmented = real_call
                ManagedResource._free_native_ptr = real_free
                real_free(builder_handle)

        self.assertEqual(result, b"\x01\x02\x03\x04")
        self.assertEqual(free_calls.count(output_address), 1)
        self.assertEqual(len(free_calls), 2)
        self.assertFalse(builder.is_valid)
        self.assertTrue(signer.is_valid)


if __name__ == "__main__":
    unittest.main()
