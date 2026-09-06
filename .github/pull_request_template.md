## Change

Describe the user-facing problem and the smallest change that addresses it.
Link a related issue if available.

## Verification

List the commands actually run and their results. Identify skipped checks and
why they were skipped; do not mark unexecuted checks as passing.

- [ ] `python scripts/run_all_tests.py`
- [ ] If bundled sources changed: `python scripts/sync_reproduction_bundle.py --check`
- [ ] If published examples changed: verify the staged publication with `python scripts/check_publication.py --ref=`

## Compatibility and evidence

- [ ] Reviewed installation/runtime compatibility and recorded platform coverage.
- [ ] Preserved original README content/media references and linked evidence where relevant.
- [ ] Recorded changed execution assumptions, scientific meaning, or comparability; no unsupported success or reproduction claims.
- [ ] Reviewed submitted logs, profiles, snapshots, and trajectories for credentials or private data.

## Limitations

Note known gaps, migration needs, and how to undo consequential changes. Mark
checklist items that do not apply and explain briefly.
