# Catalog history archive

## What is retained

The deployable Git snapshot retains all observations from the preceding 90 days
and every observation referenced by `selected_facts`. This window is evaluated
against the updater's UTC run timestamp and `observed_at`; no random sampling or
LLM interpretation is involved. Older observations are copied byte-for-byte at
the field level into `state/history/observations.sqlite3` before they are
removed from the staged catalog snapshot. The archive is append only and keyed
by a content digest as well as the original row ID, since SQLite may later reuse
an ID after compaction.

Resolved review items are archived without an age threshold; pending reviews are
always kept in the publishable catalog. The private review archive retains every
original review column and resolution note.

Model/provider identity, unresolved review items, sources, and all price records
remain in the public snapshot. Price history is not subject to observation
retention. Each published catalog remains reproducible from its Git commit and
snapshot checksums; its compact observation set is the one available in that
published version. The external archive preserves older evidence for audit and
recovery.

## Backup and restore

Keep `state/history/observations.sqlite3` with the private updater backups. Back
it up using SQLite's online backup API (or `sqlite3.Connection.backup`) while
the updater is idle; do not copy a live WAL database file alone. Retain the
archive backup alongside the matching Git commit and live SQLite backup. The
daily updater's staging DB and normal pre-refresh live DB backups remain
independent recovery points.

To restore archived observations for an audit, open the archive read-only and
select rows by `source_observation_id`, entity, field, source, or time. Resolved
review items are stored as complete JSON rows in `archived_reviews.row_json`.
To reconstruct a full historical database, restore the matching pre-refresh SQLite
backup and apply the archived rows that are absent, preserving all provenance
columns; validate foreign keys and catalog invariants before using it. Never
replace a live application database while workers are running.

## Expected growth

At the 2026-09-30 baseline, `data/snapshot` is 56 MiB in 303 shard files.
`data_observations` is 28 MiB, `pricing_records` 7.7 MiB, `selected_facts`
5.9 MiB, `provider_offerings` 4.7 MiB, and `review_queue` 1.4 MiB. The
observation retention would archive 24,159 of 104,236 rows once they age past
90 days, retaining the 80,077 current selected facts; row-proportional snapshot
projection is about 49.5 MiB. The 2,796 review rows include 2,044 pending and
752 resolved; archiving resolved reviews should lower that shard by roughly a
quarter. These estimates exclude future monitor-state rows. The checked-in
observation timestamps are all less than a day old, so the first archive run
will not reduce this baseline. Once rows age out, deployable observation data
is bounded to a rolling 90-day window plus selected facts; the private archive
grows with genuinely new evidence and is backed up separately. Monitor both
snapshot and archive sizes monthly. Unresolved review items are intentionally
not expired automatically.
