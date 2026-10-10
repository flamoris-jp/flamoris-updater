# Running the simple Updater

Linux/systemd and Python 3.12 are required. Docker apps use the local Docker daemon; Agent/Studio require reachable PostgreSQL and credentials to create their new app-owned database. These are real dependencies, not backup prerequisites.

## Updater package and bootstrap

Consume a reviewed prebuilt wheel plus its complete offline wheelhouse, or an indexed Native bundle produced by CI. For a wheelhouse installation:

```bash
sudo python3.12 -m venv /opt/flamoris-updater
sudo /opt/flamoris-updater/bin/python -m pip install --no-index --find-links /absolute/wheelhouse flamoris-updater==1.0.0
sudo /opt/flamoris-updater/bin/flamoris-updater bootstrap --root /srv/flamoris/apps
```

The paths are portable examples. An indexed bundle has its own `bin/flamoris-updater` launcher and also supplies `flamoris-updater-service`; invoke bootstrap from that protected installation. Do not clone/build source into a production app directory.

Bootstrap refuses existing state/services, provisions `flamoris-updater` as a system account, and generates `setup.json` rather than requiring manual JSON. Defaults: Web on `http://127.0.0.1:8764`, Web/helper journals under `/var/lib/flamoris-updater`, app namespaces under `/srv/flamoris/apps`. Public Web runs as the service account; the root manager exposes only a peer-checked Unix socket. systemd owns its temporary socket directory, so restart removes stale sockets. No application is needed to start Web.

Use `--directory`, `--root`, `--port` for other local paths/ports. For an HTTPS proxy/tunnel, bootstrap with `--public-origin https://updater.example.invalid`; preserve that public Host and enforce HTTPS at the proxy. Updater does not connect a tunnel or issue certificates. For initial remote setup, an SSH forward to the loopback Web port also works without client certificates.

Open the printed URL, enter the one-time setup code (expires after one hour), create the administrator and enter the HTTPS catalog URL. To renew a code before setup, run the installed `flamoris-updater-service token --config /var/lib/flamoris-updater/setup.json` as the Web service account. Setup cannot be rerun after completion. Passwords/tokens/settings never enter published release metadata or normal Job results.

## Applications

Web displays six independently selectable deployment units and release-owned settings fields. Generation Controller ships in the Generation image. Agent/Studio create only their new database/roles and use application SQL/Alembic; PostgreSQL itself is not installed or backed up. A collision with existing files, containers, units or DB/roles stops installation. There is no import/adoption route.

Installation provisions executables, retained settings/data and stopped services/containers. It ends in `awaiting_setup`, not a claim of health. Start the staged application for its own first setup, then use **verify after initial setup**. This verifies its local health/running contract and promotes the same record to `succeeded`. Updater does not certify availability of an external model/runtime.

Updates require a succeeded managed record and an explicit compatible predecessor in the recipe. They stage immutable code, reuse installed settings/data, stop/switch/start, check health and runtime identity, then retain one previous generation. Native programs have per-release virtual environments; Docker retains a stopped old container/image. Cleanup removes older executable directories/containers/images and their package cache. It never deletes configuration, runtime profiles, databases, application data or external AI/model storage. Images used by other containers are retained; cleanup failure is recorded for inspection. **Delete retained previous** is available in Web/CLI/MCP only without active/unknown Jobs.

Lost/partial effects persist `recovery_required`; they are not replayed or followed by cleanup. Inspect the Job, retained candidate and actual state before a manual, application-aware correction. No automatic DB restore or rollback after incompatible schema changes is provided. New schema handlers remain the application's responsibility; the separate Owner/migration integration requires matching contracts and is not automatically attached to a simple install.

## Commands and MCP

Create a 24-hour Bearer token with Web's **CLI/MCP token** button, or a persistent key from **MCP integration keys** for continuing automation. Save it in a mode-0600 absolute file or the client's protected credential configuration. Persistent keys remain valid until revocation, rotation or owner permission/account changes; choose read-only for inspection. Rotation requires replacing the key in the client, and immediately invalidates the old key. API clients use ordinary HTTPS/system trust, or a literal loopback HTTP endpoint through a trusted local/tunneled connection.

```bash
flamoris-updater apps --url http://127.0.0.1:8764 --token-file /absolute/private-token
flamoris-updater install --url http://127.0.0.1:8764 --token-file /absolute/private-token --application flamoris-generation-mcp --release 1.0.0 --request-key initial-generation
flamoris-updater start-setup --url http://127.0.0.1:8764 --token-file /absolute/private-token --application flamoris-generation-mcp
flamoris-updater complete-setup --url http://127.0.0.1:8764 --token-file /absolute/private-token --application flamoris-generation-mcp
flamoris-updater update --url http://127.0.0.1:8764 --token-file /absolute/private-token --application flamoris-generation-mcp --release 1.1.0 --request-key generation-update
flamoris-updater job --url http://127.0.0.1:8764 --token-file /absolute/private-token --job-id job-REPLACE
```

Only select an available compatible release; example 1.1.0 is not a publication claim. CLI install may read settings from `--settings-file` (protected JSON); ordinary operators can supply them in Web instead. `--public-origin` preserves the public Host when calling a loopback tunnel behind an HTTPS origin. `delete-previous --application ...` uses the same cleanup as Web. Reuse request keys for a lost response; changed arguments under the same key are rejected.

MCP uses `/mcp` with the same Bearer token. See [MCP](MCP_API.md). [Installation](INSTALL.md) describes prebuilt candidates/catalogs. Public releases/full real-host acceptance are not prerequisites for controlled disposable installation tests.

## Updater self-update

New bootstrap also installs `flamoris-updater-supervisor.service` from the original protected installation. Keep that installation: the independent root supervisor updates Web/manager, not itself. Existing bootstraps without it report unsupported; this feature does not silently rewrite an older bootstrap.

Select a compatible Updater release in Web, or use `self-status` / `self-update --release 1.1.0 --request-key updater-1.1` with the same endpoint/token options. Only the configured catalog can supply release/artifact/platform bindings. The supervisor verifies the indexed bundle, stops Web/manager, probes both existing journals read-only, switches their fixed units, starts them, and verifies both running versions and runtime paths. It preserves configuration, authentication and history; no journal/DB schema upgrade, rollback or application operation is performed. Interrupted/failed Jobs stop at `recovery_required` without replay.

Web/MCP are unavailable briefly during replacement. Keep the returned Job ID and reconnect to the same endpoint/key to inspect it. If the request response is lost, reuse its request key; no second update is created. The client must handle connection loss/reconnection. Updater does not maintain a tunnel or configure an external MCP client. See [self-update and logging review](SELF_UPDATE.md).

## Advanced compatibility boundary

The older explicit `serve --config CoordinatorConfig`, host/helper and recovery-controller commands remain for application-owned migration/signed multi-host integration. Their keys, Owner services and independent recovery controller are not required by bootstrap. Neither their plans nor Owner DBs are imported into simple management. Backup/restore operations and fields are removed from Core/Owner/planner/runner; old SDK/configs need a matched rebuild. Pinned supervisor replacement and database schema compatibility still need separately reviewed maintenance; simple app cleanup provides no system rollback.

## Logs, placement and Updater downtime

AI can read ordered effect evidence with `updater_managed_log_get` and recorded
current/candidate/previous placement with `updater_managed_layout_get`, using a
read-only key scoped to the application. See [diagnostics](DIAGNOSTICS.md) for
pagination, secret handling, offline exports and failure uncertainty.

If Updater itself stops, its MCP cannot inspect evidence or recover it. Use an
independent administrator channel and the documented manual investigation
procedure. Check queued Jobs before restarting services; do not assume restart
clears unknown effects or recovery blockers.
