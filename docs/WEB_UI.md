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
