# Roadmap

## Native Resource Ownership Follow-Ups

The generic consume-first ownership fix is in `7ba8615` and is integrated into
the functional Python branch. Follow-up `a303db8` documents that guarded
cleanup can change the sticky native error slot even though Python raises the
original snapshotted error; it adds a direct non-NULL typed-pointer test and
clarifies that a `PointerInUse` release can defer the native object's drop.
These are documentation and test improvements, not a new ABI or signing policy.

Remaining work is separate from this integration:

- Exercise a real opaque-native `PointerInUse` with an outstanding checkout
  guard. Confirm that guarded release removes only that handle's registry entry,
  defers the object drop until the last guard exits, and does not change the
  Python exception. The existing sticky-slot assertions are mocked; add a
  real-native check that distinguishes the raised exception from the native
  error slot after cleanup. Do not generalize the opaque-ID guarantee to stock
  native, whose raw allocation addresses can be reused.
- Stock c2pa-rs 0.91.0 Windows x64 ownership, unit/ladder and threaded suites
  passed in [mstattma/c2pa-python Actions run 36775608167](https://github.com/mstattma/c2pa-python/actions/runs/36775608167).
  Stock Windows ARM64 was outside this ownership patch's qualification scope;
  evaluate that ownership lane separately from legacy Windows ARM64 wheel jobs.

Qualify each new merged Python head against the pinned consolidated native
`203dc08d` before updating the functional branch. These follow-ups do not
authorize a dev5 release or change immutable historical release evidence.
