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
