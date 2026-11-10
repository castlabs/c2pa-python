# Single-file fragmented fixture

`single_file_fragments.mp4` contains an initialization prefix (`ftyp`/`moov`)
and three H.264 `moof`/`mdat` fragments in one file. It is synthetic test media,
not separate resolution encodes. The Python smoke signs two copies of these
same bytes; it does not claim multi-resolution coverage.

The bytes match c2pa-rs `sdk/tests/fixtures/single_file_fragments.mp4` exactly.

- Size: 3,812 bytes
- Git blob: `1a4813c4c60473c619665e130c75f4f63b071b01`
- SHA-256: `0dcc2720b3c217e192b2bf7205f8f3675eac417f02f306db3dfe73713660f968`

The source README records generation with FFmpeg 6.1.1 and its synthetic
`testsrc2` source:

```sh
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=32x32:rate=2 -t 3 \
  -c:v libx264 -threads 1 -g 2 -bf 0 \
  -movflags +empty_moov+frag_keyframe+default_base_moof+global_sidx \
  -y single_file_fragments.mp4
```

Tests use the committed bytes and existing test-only ES256 key/certificates in
the parent directory. They need neither FFmpeg nor an external timestamp server.

## Per-fragment `sidx` fixture

`single_file_fragments_sidx.mp4` is the same synthetic source muxed with a
per-fragment `sidx` before every `moof` (version 1 boxes), the layout
byte-range HLS packagers cut at. `tests/test_fragment_at_offset.py` signs it and
verifies each Merkle-uuid-delimited slice at its absolute offset.

The bytes match c2pa-rs `sdk/tests/fixtures/single_file_fragments_sidx.mp4`
exactly (castlabs/c2pa-rs commit `ec9ac2f6917201a5cc69c0ef12f756228e359da2`,
branch `feat/trusted-vsi-fragment-offset`).

- Size: 3,892 bytes
- Git blob: `3158e05962c808fd25be713bb8d7f84214275233`
- SHA-256: `8d95ae1959740b8fd02d30ad9e4eb04da7dc26869c14605677c084ce9b03ccff`

```sh
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=32x32:rate=2 -t 3 \
  -c:v libx264 -threads 1 -g 2 -bf 0 \
  -movflags +empty_moov+frag_keyframe+default_base_moof+dash \
  -y single_file_fragments_sidx.mp4
```
