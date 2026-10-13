# Updater Web

The standalone screen starts immediately without creating an administrator, logging in or issuing a token. It has no Studio dependency.

1. Register each repository's catalog URL; multiple catalogs can coexist.
2. Select an app/release and complete its settings form.
3. Follow installation status; start the application for its own setup and verify afterward.
4. Update that app while retaining its settings/data and one previous executable version.
5. Inspect durable Jobs/history, or update Updater itself through the pinned supervisor.

Each repository owns its releases and payloads. Registration downloads only catalogs, installation/update downloads only selected app/platform payloads, and unregistering a catalog does not delete apps. One unavailable source does not prevent checking other repositories. Conflicting release definitions are rejected and previous checked snapshots remain available.

The frontend is an unprivileged loopback service. Exact Host/supplied Origin checks, bounded JSON and CSP remain; password/session/CSRF-token/key workflows and their endpoints are removed. See [transport](TRANSPORT.md), [running](RUNNING.md) and [self-update](SELF_UPDATE.md).

## Operator feedback in 1.0.8

The sticky header shows the running server's hostname and Updater version from
the existing `/health` response, plus current connection status. Four bounded
colour choices are saved in browser local storage, keyed by origin, public
prefix and actual hostname. They affect this browser's view only; disabled
browser storage still permits changing the current view.

Read-only progress polling handles HTML/invalid JSON and shows the HTTP status
and requested API without displaying response bodies. Connection messages clear
after a complete successful refresh. Operation failures are separate, dismissible
messages and are not erased by a background refresh. Lost mutation responses
are never automatically resent; the operator checks durable Jobs/history. After
a runtime version change the page reloads to fetch current assets.

Setup buttons have visible spacing, processing labels and local completion or
failure feedback. Starting a process is not reported as health verification;
the second button still performs the actual running/health checks. Settings
with the catalog's `generate` flag show that an empty input is generated. Typed
secret values remain local to the form and are preserved during progress polling.

Catalog switching uses existing registration/removal: register the new URL
before removing the old source. Removal retains installed apps/settings/history;
changing an immutable app/release/platform description remains forbidden. The
screen also shows the recorded Updater executable placement; self-updates stage
under the bootstrap state directory's `releases`, not necessarily `/opt`.

GitHub connection settings remain deferred in
[Issue #32](https://github.com/flamoris-jp/flamoris-updater/issues/32). No new
authentication or log-directory provisioning is introduced.

## Compact management and Job Search (published 1.0.13)

Catalog Management is collapsed initially. It preserves every registered URL,
including old snapshots, with source status and explicit removal. Removal only
drops that source's update candidates; installation/settings/data/history and
immutable bindings stay retained. Previous executable deletion remains on each
installed app. Available releases are sorted newest first; installed/older
versions are excluded from update choices. No cleanup happens from hiding rows.

The server captures an insertion watermark when serving the management HTML.
Only Jobs inserted after that boundary appear in the current view; old active,
failed and unsettled Jobs remain accessible from **Job Search** (`/jobs` under
the public prefix). Every tab/reload has its own boundary. Polling/reconnection
preserves it; browser/server clock differences and same-second creation do not
affect membership. Hidden unresolved self-update Jobs still disable update
controls. Both views page 20 results at a time.

Job Search filters on application (including all apps, Updater, and unassigned
operations) and half-open creation period. Inputs/display use the browser's
labeled timezone. Newest-first cursor paging bounds server responses/rendering;
job links open existing recorded progress and paged effect evidence. Empty,
invalid-period and connection errors are visible. Search/navigation are read-only
and never re-execute a Job. Searches do not call external catalog sources.

Opening/reloading management first shows saved information, then performs one
catalog check, as does Refresh. Progress polling uses retained snapshots only.
Discovery includes the official Updater latest catalog; installed app origins
come from an immutable recorded recipe's GitHub payload URLs when all downloads
belong to the same repository, or an unambiguous matching registered snapshot.
An app ID is never used to guess a repository. Unsupported/ambiguous origins
are shown and require manual registration. GitHub origins use that repository's
`releases/latest/download/catalog.json`; custom HTTPS catalogs retain their
registered URL. These rules also handle initial installation snapshots.

Sources are deduplicated and downloaded once per requested refresh, including
newly discovered sources. Each failure preserves its last verified snapshot,
last-success time and bounded error code while other sources continue. Existing
private GitHub access is reused; missing access is labeled. Live refresh does
not replace typed settings drafts or replay lost operations.

An explicit URL removal is durable and suppresses that exact automatic source
until manual re-registration. Removing an old tagged snapshot does not remove
a separately registered latest URL for the same repository. Both are visible
inside Catalog Management; neither operation deletes app executables or history.
Published recipes/snapshots are not rewritten for source discovery.

This behavior ships in published 1.0.13. Managed runtime rollout is recorded
in [progress](../PROGRESS.md); production browser acceptance remains separate.
