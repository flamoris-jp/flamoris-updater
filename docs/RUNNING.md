# Running Updater

Linux/systemd and Python 3.12 are required. Docker apps use the local daemon. Agent/Studio need reachable PostgreSQL and their application-owned initialization credentials.

## Bootstrap

Install a reviewed prebuilt Updater wheel/wheelhouse or indexed bundle, then run its protected launcher:

```bash
sudo /absolute/installation/bin/flamoris-updater bootstrap --root /srv/flamoris/apps
```

Bootstrap provisions a service OS account, private journals and three units: unprivileged Web, root local manager and pinned root supervisor. It refuses existing state/services and prints the URL. There is no setup code, administrator creation, password, login or key provisioning. Existing registered catalogs/installations keep their records when the package is replaced; do not rerun bootstrap over an existing installation.

Defaults are loopback `http://127.0.0.1:8764`, state `/var/lib/flamoris-updater`, app namespaces `/srv/flamoris/apps`. Use `--directory`, `--root`, `--port` to select alternatives. `--public-origin https://updater.example.invalid --base-path /updater` supports an external proxy/tunnel. Preserve the public Host and path. Updater does not configure that connection or certificates. See [transport](TRANSPORT.md).

## Catalogs and applications

Open the screen and register each repository's HTTPS catalog URL. A catalog can describe one app, one platform or several releases; all six applications/both CPUs are never required. A shared catalog can also point at assets in separate repositories. Only the selected application's matching CPU payloads are downloaded during installation/update. Each repository builds and publishes its own artifacts; this repository does not aggregate them.

Registering another catalog requires only that new source to be available. Refresh checks each source independently, displays errors and keeps the last checked snapshot for failed sources. Removing a catalog leaves its installed apps/settings/data/history intact. Conflicting descriptions of the same immutable app/release/platform are rejected.

Choose an app and release, enter its settings and install. Start the staged app for its own setup, then verify it. Installation ends at `awaiting_setup`, becoming `succeeded` only after verification. Updates stage new code beside old, retain settings/data, stop/switch/start and verify. Only after success are older executables removed, keeping current plus one previous. Unknown/interrupted Jobs stop at `recovery_required` without replay. DB/schema transformations remain application-owned. Existing unmanaged applications are not imported.

## CLI and MCP

No Bearer token or token file is used. Web, CLI and MCP call the same manager.

```bash
flamoris-updater apps --url http://127.0.0.1:8764
flamoris-updater install --url http://127.0.0.1:8764 --application example-app --release 1.0.0
flamoris-updater start-setup --url http://127.0.0.1:8764 --application example-app
flamoris-updater complete-setup --url http://127.0.0.1:8764 --application example-app
flamoris-updater update --url http://127.0.0.1:8764 --application example-app --release 1.1.0
flamoris-updater job --url http://127.0.0.1:8764 --job-id job-REPLACE
```

The versions/application above are illustrative. CLI install can use a protected `--settings-file`; Web supplies the same fields. Reuse `--request-key` after a lost response. `--public-origin` preserves Host for a loopback tunnel to a configured HTTPS origin. Catalog operations are available via `call --tool updater_catalog_add` / `updater_catalog_remove` / `updater_catalogs_list` with JSON arguments from a file/stdin. MCP is `/mcp` below any configured prefix and needs no Updater credentials. See [API](MCP_API.md).

## Self-update and investigation

The pinned supervisor stages and verifies compatible Updater bundles and replaces Web/manager while preserving settings/history. Keep its original installation; supervisor replacement is administrator maintenance. Web/MCP temporarily disconnect and reconnect at the same URL. Logs/layout and durable Job IDs remain available. See [self-update](SELF_UPDATE.md) and [diagnostics](DIAGNOSTICS.md). Server Manager remains the source for actual infrastructure state.

The administrator-only `install-profile` path and internal Core/Owner migration integration remain separate. Ordinary `serve --config` now uses generated `BootstrapConfig`, not the old signed multi-host Web configuration. Removed account/key commands and old grant/plan APIs are not normal operator interfaces.
