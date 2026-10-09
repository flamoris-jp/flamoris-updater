# Fresh installation

Install Updater first; then use its **local administrator CLI** to install AI-side
packages directly at **1.0.0** and GPU Node Manager at **1.2.0**. No 0.1/1.1
installation, baseline conversion, backup, running application Owner, Coordinator,
Updater account or client certificate is required by this route.

The six installation targets are Agent, Studio, Intelligence MCP, Generation MCP,
MCP Hub and native GPU Node Manager. Generation Controller 1.0.0 is a component
inside the Generation image, not a seventh independently started container.

## Install Updater before applications

Use Python 3.12 and the wheel/dependency set or verified native bundle produced by
Updater CI. Install it in a root-owned dedicated environment outside application
directories. For an offline wheel set, for example:

```bash
sudo /usr/bin/python3.12 -m venv /opt/flamoris-updater/venv
sudo /opt/flamoris-updater/venv/bin/python -m pip install --no-index --find-links /absolute/updater-wheels flamoris-updater==1.0.0
```

These paths are illustrative; use the approved host-specific layout. No Updater
Web/Coordinator service needs to start for local installation. Administer locally
or through an existing SSH session. OS root privileges authorize Docker, database
provisioning and systemd changes; the installer does not introduce another login.

## Prepare a protected host profile

Export `InitialInstallConfiguration.schema.json` with
`python scripts/export_schemas.py --output dist/schemas`. The source models in
`src/flamoris_updater_adapters/install.py` are authoritative. Use one profile per
host, containing only applications assigned to that host. Store profile JSON,
inputs and all ancestor directories under root control; private inputs and the
profile must have mode 0600. Do not commit host profiles or credentials.

Each profile contains `install_profile_version: 1`, the exact `expected_hostname`,
`platform` (`linux/amd64` or `linux/arm64`), an independent `state_directory` and
`applications`. Each application declares its fixed release, new storage roots,
configuration copies and loopback HTTP readiness endpoint. Modes in JSON are
decimal (`384` = 0600, `488` = 0750). Every input file has an absolute path and
`sha256:<64 hex digits>` digest; set `private: true` for secrets/environment files.
Environment files use literal duplicate-free `KEY=value`, without shell quoting,
expansion or `export`.

Docker targets supply a local `docker save` archive, its digest, immutable
`image_id`, a new `container_name`, copied `environment_file`, mounts and network.
Images must carry `org.opencontainers.image.title` and `.version` matching the
target, Linux architecture matching the profile, and no anonymous volumes.
Generation also requires `net.flamoris.components` containing
`{"flamoris-generation-controller":"1.0.0"}`. The manual
`initial-candidates.yml` workflow builds candidates and reports their actual
package versions, source revisions, image IDs and archive hashes; it does not
publish releases or mark them accepted for deployment.

The installer pins Docker commands to the local Unix socket rather than the
operator's selected Docker context. Keep the copied environment file root-owned,
mode 0600, inside an administrator-owned storage root.
All writable mounts must belong to newly declared application roots. External
model/runtime storage can be mounted read-only and is never created, deleted or
chowned. Declare writable output/thumbnail/state roots with UID/GID 10001 where
the application's container requires them. Containers run as 10001, with a
read-only root filesystem and dropped capabilities. Host-network Agent,
Intelligence and Generation must explicitly bind loopback in their environment.
Studio's fixed wildcard listener requires `network: "bridge"` and an explicit
loopback publication for port 5087; its DB host must be reachable from that
container. MCP Hub uses `/mcp` initialization rather than a nonexistent healthz;
its application client token remains an application credential, not Updater auth.

Agent and Studio require a `database` declaration: a new database, separate owner
and runtime roles, private administrator DSN and role-password files. The runtime
environment must match that database/role/password and the administrator's host
and port. PostgreSQL itself already exists and is not replaced by this installer.

- Agent requires `flamoris_ai_owner` and `flamoris_ai_app`. Supply its own
  `db/01_schema.sql`, followed by migrations 002–005 in order from the pinned
  Agent source. These initialize an empty current schema; the old comment in the
  base SQL is not a requirement to install Agent 0.1. Supply separately reviewed
  initial identities/model grants if needed; example seeds are not production
  identities and are not applied automatically.
- Studio supplies a private `studio_migration_environment` using the new owner
  credentials. Its installed image runs `alembic upgrade head`. The runtime role
  receives schema usage, table DML and sequence permissions, not schema ownership.

Native GPU Node Manager supplies a protected Python 3.12 executable, a new `venv`
inside its new application roots, an offline wheel set and root-owned systemd unit
files. Exactly one `ExecStart` must run that venv's `gpu-node-manager`; other Exec
hooks/continuations are refused. Provide reviewed runtime/identity configuration
and loopback listener arguments. No runtime/model installation or GPU activation
is performed by readiness checking. Private deployment overlays remain private.

## Check, install and inspect

```bash
sudo /opt/flamoris-updater/venv/bin/flamoris-updater install --profile /absolute/host-install.json --check
sudo /opt/flamoris-updater/venv/bin/flamoris-updater install --profile /absolute/host-install.json
sudo /opt/flamoris-updater/venv/bin/flamoris-updater install --profile /absolute/host-install.json --status
```

`--check` validates host/root/platform, input hashes and absence of target paths,
containers, units, databases and roles without installing. The apply command
checks all applications before effects, records each step before executing it,
copies configuration, installs artifacts, initializes databases, starts services
and confirms readiness/running state. Existing targets stop the operation; this
command never cleans an existing deployment. Any separately authorized cleanup
must use an exact inventory and exclude shared runtimes/models/OS services.

A successful run cannot be replayed. A failed or uncertain step records
`recovery_required`; inspect recorded and actual state instead of changing the
state directory or rerunning against partial resources. There is no automatic
deletion, reverse migration or backup/restore in this fresh-install route.

## Boundary with ordinary updates

This local initial-install record does not enroll an application into the older
remote Coordinator protocol. Existing ordinary update/Owner, signed-catalog and
remote mTLS contracts remain implemented separately in [RUNNING.md](RUNNING.md).
Remote update enrollment and real-host acceptance require further integration;
successful fresh installation alone is not evidence those are ready. A future
local ordinary-update route can use OS/SSH administration without mandatory
client certificates. Release provenance/integrity checks remain useful regardless
of whether an operator login or transport certificate is needed.
