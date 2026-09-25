"""Explicit real-native lanes, run in a fresh process with an isolated package.

See docs/ladder-signing.md for commands. Neither lane skips missing capability.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_lane(args):
    import c2pa.c2pa as binding
    from c2pa import Builder, C2paError, C2paSignerInfo, Reader, Signer
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    loaded = Path(binding._lib._name).resolve(strict=True)
    expected = Path(os.environ["C2PA_LIBRARY_NAME"]).resolve(strict=True)
    assert loaded == expected, (loaded, expected)
    assert Path(binding.__file__).resolve().parent == expected.parent
    assert digest(loaded) == digest(args.library), "Library changed during staging"
    print(json.dumps({
        "lane": args.lane, "source_library": str(args.library),
        "loaded_library": str(loaded), "sha256": digest(loaded),
        "sdk_version": binding.sdk_version(),
        "has_sign_ladder": binding._HAS_SIGN_LADDER,
    }), flush=True)
    assert binding._HAS_SIGN_LADDER == (args.lane == "candidate"), (
        "Candidate requires c2pa_builder_sign_ladder; stock must lack it")
    if args.lane == "candidate":
        export = binding._lib.c2pa_builder_sign_ladder
        assert export.restype is binding.ctypes.c_int64
        assert export.argtypes == [
            binding.ctypes.POINTER(binding.C2paBuilder),
            binding.ctypes.POINTER(binding.C2paSigner),
            binding.ctypes.POINTER(binding.ctypes.c_char_p),
            binding.ctypes.POINTER(binding.ctypes.c_char_p),
            binding.ctypes.c_size_t,
            binding.ctypes.POINTER(
                binding.ctypes.POINTER(binding.ctypes.c_ubyte)),
        ]

    definition = {
        "claim_generator_info": [{"name": "ladder-binding-test"}],
        "assertions": [{"label": "c2pa.actions", "data": {"actions": [{
            "action": "c2pa.created",
            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
        }]}}],
    }
    certs = (FIXTURES / "es256_certs.pem").read_bytes()
    key = (FIXTURES / "es256_private.key").read_bytes()
    info = C2paSignerInfo(alg=b"es256", sign_cert=certs,
                          private_key=key, ta_url=None)
    with Signer.from_info(info) as signer:
        with Builder(definition) as builder:
            if args.lane == "stock":
                try:
                    builder.sign_ladder(signer, ["in.mp4"], ["out.mp4"])
                except C2paError.NotSupported as error:
                    assert "c2pa_builder_sign_ladder" in str(error)
                else:
                    raise AssertionError("Stock capability error was not raised")
                builder._ensure_valid_state()
            ordinary = Path("ordinary.jpg")
            assert builder.sign_file(FIXTURES / "A.jpg", ordinary, signer)
            assert builder._lifecycle_state == binding.LifecycleState.CLOSED
        signer._ensure_valid_state()
        with Reader(ordinary) as reader:
            assert reader.get_validation_state() == "Valid", reader.json()
        print("ordinary signing and validation passed", flush=True)
        if args.lane == "stock":
            return

        assert args.native_fixtures is not None, "--native-fixtures is required"
        fixtures = [args.native_fixtures / name for name in (
            "single_file_fragments.mp4", "single_file_fragments_absolute.mp4")]
        before = [digest(path) for path in fixtures]
        print(json.dumps({"fixtures": dict(zip(map(str, fixtures), before))}),
              flush=True)
        sources = [Path(path.name) for path in fixtures]
        for source, fixture in zip(sources, fixtures):
            shutil.copy2(fixture, source)
        private_key = serialization.load_pem_private_key(key, password=None)

        def callback(data):
            return private_key.sign(data, ec.ECDSA(hashes.SHA256()))

        with Signer.from_callback(callback, binding.C2paSigningAlg.ES256,
                                  certs.decode()) as callback_signer:
            for label, active_signer in (("info", signer),
                                         ("callback", callback_signer)):
                dests = [Path(f"{label}-{i}.mp4") for i in range(len(sources))]
                with Builder(definition) as builder:
                    manifest = builder.sign_ladder(active_signer, sources, dests)
                    assert manifest
                    assert builder._lifecycle_state == binding.LifecycleState.CLOSED
                active_signer._ensure_valid_state()
                manifests = []
                for dest in dests:
                    assert manifest in dest.read_bytes()
                    with Reader(dest) as reader:
                        assert reader.get_validation_state() == "Valid", reader.json()
                        data = json.loads(reader.json())
                        manifests.append(data["manifests"][data["active_manifest"]])
                assert manifests[0] == manifests[1]

                # Change media payload, not box structure or the signed manifest.
                tampered = bytearray(dests[0].read_bytes())
                offset = 0
                while tampered[offset + 4:offset + 8] != b"mdat":
                    size = int.from_bytes(tampered[offset:offset + 4], "big")
                    assert size >= 8
                    offset += size
                    assert offset + 8 < len(tampered)
                tampered[offset + 8] ^= 1
                dests[0].write_bytes(tampered)
                with Reader(dests[0]) as reader:
                    assert reader.get_validation_state() == "Invalid", reader.json()
                print(f"{label} ladder signing, shared manifest, and tamper checks passed",
                      flush=True)

        # Native path validation failure still ends this builder's single use.
        existing = Path("existing.mp4")
        sentinel = b"existing destination must not be overwritten"
        existing.write_bytes(sentinel)
        for label, dests in (
            ("source alias", sources),
            ("duplicate destination", [Path("duplicate.mp4")] * 2),
            ("existing destination", [existing, Path("new.mp4")]),
        ):
            with Builder(definition) as builder:
                try:
                    builder.sign_ladder(signer, sources, dests)
                except C2paError:
                    assert builder._lifecycle_state == binding.LifecycleState.CLOSED
                else:
                    raise AssertionError(f"Native layer accepted {label}")
            signer._ensure_valid_state()
            assert existing.read_bytes() == sentinel
            assert [digest(path) for path in sources] == before
            print(f"{label} refusal and lifecycle checks passed", flush=True)

        calls = []

        def fail_callback(data):
            calls.append(len(data))
            return b""

        with Signer.from_callback(fail_callback, binding.C2paSigningAlg.ES256,
                                  certs.decode()) as failing_signer:
            with Builder(definition) as builder:
                try:
                    builder.sign_ladder(failing_signer, sources,
                                        [Path("failed-0.mp4"), Path("failed-1.mp4")])
                except C2paError:
                    assert calls, "Signing failed before invoking the callback"
                    assert builder._lifecycle_state == binding.LifecycleState.CLOSED
                else:
                    raise AssertionError("Native layer accepted a failed callback")
            failing_signer._ensure_valid_state()
        print("callback failure and lifecycle checks passed", flush=True)
        assert [digest(path) for path in sources] == before


def main():
    if sys.flags.optimize:
        raise SystemExit(
            "Native ladder verification requires assertions; "
            "rerun without -O/-OO or PYTHONOPTIMIZE.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--lane", choices=("stock", "candidate"), required=True)
    parser.add_argument("--native-fixtures", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.library = args.library.resolve(strict=True)
    if args.native_fixtures is not None:
        args.native_fixtures = args.native_fixtures.resolve(strict=True)
    if args.child:
        run_lane(args)
        return
    with tempfile.TemporaryDirectory(prefix="c2pa-ladder-") as temp:
        root = Path(temp)
        package = root / "c2pa"
        shutil.copytree(ROOT / "src" / "c2pa", package,
                        ignore=shutil.ignore_patterns("libs", "__pycache__"))
        staged = package / args.library.name
        shutil.copy2(args.library, staged)
        env = os.environ.copy()
        env.pop("PYTHONOPTIMIZE", None)
        env["PYTHONPATH"] = str(root)
        # Existing loader seam, with an absolute filename and a checked result.
        env["C2PA_LIBRARY_NAME"] = str(staged)
        command = [sys.executable, str(Path(__file__).resolve()),
                   "--child", "--lane", args.lane, "--library", str(args.library)]
        if args.native_fixtures is not None:
            command += ["--native-fixtures", str(args.native_fixtures)]
        subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
