# Application entry transition

The six AI packages enter managed updating at 1.0.0. GPU Node Manager enters at
1.2.0. Existing release labels are v0.1 and v1.1 respectively. GPU v1.1 points
to a source distribution reporting 1.0.0; a tag is not installed package evidence.

## Source and operational status

Application adoption source is under review. This implementation does not
publish releases, install trust keys/profiles, change production data, or update
hosts. A signed candidate and private protected deployment configuration are
required before executing any transition. The PostgreSQL sandbox has a real CI
integration job; skipped local integration tests are not restore evidence.

`packages/update-core` builds the MCP-independent `flamoris-update-core`
distribution from the same Core sources. Applications install that SDK; the
Updater coordinator and entry CLI remain in their separate environment. Do not
install the full Updater into an application's MCP 2 environment. Do not install
both distributions into the same environment: they share Core namespaces.

## Application-owned resources

| Application | Required resource classes | Current accepted schema identifiers |
| --- | --- | --- |
| Agent | configuration, database | agent-config-1; 005_model_continuations |
| Studio | configuration, database | studio-config-1; 20261005_12 |
| Intelligence | configuration | intelligence-config-1 |
| Controller / co-hosted Generation MCP | configuration, recipes, outputs | controller-config-1; native-recipes-1; generation-assets-1 |
| Hub | configuration | hub-catalog-1 |
| GPU Node Manager | configuration, evidence | gpu-profiles-1; runtime-evidence-1 |

The packaged Controller is updated with its hosting Generation MCP artifact.
It is not another live process/JobStore. Bind it as an embedded component and
preserve the one Controller authority. No competing owner may claim the same
physical resource. Extra provider-owned retained input directories require
their own writer fencing/backup contract; do not silently omit them from an
installation profile. A profile outside this implemented resource contract is
unsupported and must remain blocked pending its explicit extension.

These transitions preserve existing schemas. They do not initialize databases,
run Alembic upgrades, erase assets, rebuild persona, or reconcile unknown work.
Older schemas must use their application's existing reviewed migration procedure
before this entry path. Unknown reservations remain blockers, including retired
generation reservations. No provider inference or automatic replay is performed.

## Provisioning before use

Each application has a separate `*-update-owner --config /protected/owner.json`
entrypoint. OwnerConfiguration declares its DeploymentProfile, exact TreeBinding
and PostgresBinding resources, private state/backup directories, protected signed
manifest files and pinned release/host receipt keys. ServerConfiguration adds
the listen address, mTLS CA/certificate/key and allowed client DER certificate
SHA256 fingerprints. There is no product UI integration or arbitrary command
route. The dedicated Updater Web/CLI/MCP retain orchestration.

Run the Owner under the same dedicated account as the application. Its private
state is shared with that application via a fixed writable binding. Its signed
configuration and code are protected from application edits. Owner availability
is independent of stopping/replacing the application executable/container.
PostgreSQL Owners run as non-root, with a private owner-only DSN to a maintenance
role. That role must be distinct from the bound writer roles. All writer roles
and timers/external writers must be declared and fenced. The fixed `pg_bin`
must match the production server major version.

`FLAMORIS_UPDATE_REQUIRED=1` and `FLAMORIS_UPDATE_STATE=/private/owner-state`
are mandatory in a managed application's protected environment. A missing gate
fails closed. Admission is durable across processes and restarts; uncertainty
never expires by elapsed time. Managed service startup waits while the gate is
closed, without starting DB/provider work, and records its package boot identity.
Owner inspections never masquerade as a service boot. Set the Owner's environment
to the same protected application settings, including Intelligence configuration.

Tree snapshots refuse symlinks, hardlinks, FIFOs, devices and privileged modes.
They bound bytes and include at most 4096 members (directories included), then
verify an isolated copy's bytes, ownership and permissions. Model/cache trees
using links are not included by assumption; bind preserved external resources
through a reviewed profile rather than copying or normalizing them.

PostgreSQL backup fences writers, records data/schema/ACL/role membership and
verifies a real restore into a disposable local cluster inside bubblewrap's
empty network/PID namespace. Production DSN/passwords are not passed to the
probe; copied roles have NOLOGIN and no passwords. Only immutable SDK/Python
code, backup bytes and a disposable directory are mapped. Credentials and
deployment configuration must be outside the mapped code prefixes. User namespace
support and protected PostgreSQL/bubblewrap executables are required; no fallback
to an unisolated production connection is provided.

Private HelperConfig binds fixed Docker or native lifecycle. Docker retains the
previous stopped container, uses a digested verified image, fixed mounts/user,
resource limits and explicit ports. Host networking requires explicit
`allow_host_network=true` in the protected binding. Native entry requires an
already provisioned fixed systemd unit and protected release pointer; existing
legacy units/venvs are not silently rewritten. Preserve deployment overlays and
their complete matched dependency set in a native candidate. GPU Node Manager
remains native and uses its existing RuntimeManager and host-wide lock.

## Independent execution

Stop the legacy service and all its external writers through the existing
authorized maintenance procedure. Legacy binaries cannot honor the new SDK gate.
The standalone CLI refuses an active legacy container/unit or unresolved work.
Never treat a healthy endpoint or a missing PID as proof of writer fencing.

Use the read-only `source` command to obtain the stopped source binding digest;
review it against the approved installed artifact before recording it.

Prepare a root-owned EntryConfiguration containing `helper_config_file`,
`deployment_id`, `manifest_file`, `baseline_tag`, `baseline_revision`, and the
reviewed `expected_source_state_digest`. The source binding ties the actual old
container/image/configuration or native unit/pointer to the approved baseline;
baseline_revision is an operator-recorded provenance assertion, not inferred from
package version. The candidate Manifest and `.sig` are verified against pinned
application release keys. Release publication and trust provisioning are separate.

```bash
flamoris-updater-entry --config /protected/entry.json plan --output /private/entry-plan.json
flamoris-updater-entry --config /protected/entry.json apply --plan /private/entry-plan.json --confirm sha256:REVIEWED_PLAN_DIGEST
flamoris-updater-entry --config /protected/entry.json status --job ENTRY_JOB_ID
```

The 15-minute plan binds actual observation, resource/profile/configuration,
source state and signed target. Apply rechecks it before durable claims/intents.
It prepares, claims the owner job, closes/drains admission, stops, snapshots,
verifies isolated restore, activates, validates, reopens and finalizes. Activation
requires both host-signed artifact evidence and matching maintenance boot.

Failure retains claims/history and requires explicit reconciliation. Re-running
the same plan never repeats an effect. Status remains available for investigation.
There is no automatic rollback/data restore or multi-host atomicity claim.
Verified `standalone_transition` evidence permits the ordinary coordinator's
read-only enrollment afterward. Normal updates use that coordinator; the entry
CLI cannot re-enter an already enrolled installation.
