# Updater Web

The standalone screen starts immediately without creating an administrator, logging in or issuing a token. It has no Studio dependency.

1. Register each repository's catalog URL; multiple catalogs can coexist.
2. Select an app/release and complete its settings form.
3. Follow installation status; start the application for its own setup and verify afterward.
4. Update that app while retaining its settings/data and one previous executable version.
5. Inspect durable Jobs/history, or update Updater itself through the pinned supervisor.

Each repository owns its releases and payloads. Registration downloads only catalogs, installation/update downloads only selected app/platform payloads, and unregistering a catalog does not delete apps. One unavailable source does not prevent checking other repositories. Conflicting release definitions are rejected and previous checked snapshots remain available.

The frontend is an unprivileged loopback service. Exact Host/supplied Origin checks, bounded JSON and CSP remain; password/session/CSRF-token/key workflows and their endpoints are removed. See [transport](TRANSPORT.md), [running](RUNNING.md) and [self-update](SELF_UPDATE.md).
