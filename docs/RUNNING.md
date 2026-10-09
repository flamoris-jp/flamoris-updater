# Running and releasing v1

This is the source implementation procedure. No release, production credentials or real deployment is supplied. Linux/systemd, Python **3.12**, a local persistent filesystem and an audited application lifecycle owner are required. Use the [README](../README.md) setup for development.

## Provision before starting

1. Obtain current deployments, physical persistence identities, all writers and provider relationships through Server Manager and application owners. Record private details outside this repository. Match each physical namespace to one Resource and one owner. Borrowed resources share the owner's schema target; only the owner migrates/snapshots/restores them.
2. Use an already recorded managed installation for updates. Unmanaged deployments cannot be imported. The migration runner handles application-owned schema changes, not entry into management. The new simple installation/setup workflow is separate work.
3. Provision separate Ed25519 release, catalog, coordinator-authority, recovery-controller and host-receipt keys. Pin application/domain, purpose, channel and revocation state explicitly. Private signer files accept raw 32-byte or Ed25519 PEM; protect private files with owner-only permissions. Never put private keys in JSON, notes, browser assets or this repository.
4. Provision approved HTTPS release/catalog origins. Private CA and client certificates are not used; configure local Owner sockets and loopback host connections as described in [transport](TRANSPORT.md). Host receipt IDs must equal host IDs; all hosts participating in epoch handoff need the full receipt-key set. Each host pins both coordinator and stable controller public keys. Protect credential files and their ancestor directories against replacement by service users or unrelated accounts.
5. Install independently pinned stable helper/controller binaries and state outside replaceable coordinator release directories. Configure root-owned service unit files, indexed artifacts, staging quotas, private local journals and fixed active pointers. A recovery controller must survive coordinator failure; merely installing its script inside the current coordinator bundle is insufficient.
6. Supply exact JSON configs matching the exported schemas. Do not paste the illustrative contract digests into production. Derive `binding_revision` as SHA-256 of the canonical serialized Native/Docker binding (`wire.dumps(binding)`), and `physical_binding_digest` from the verified physical namespace identity. Both coordinator and local helper register the same approved resources/profiles. The application owner must report matching actual physical digests.

Export schemas with:

```bash
python scripts/export_schemas.py --output dist/schemas
```

`CoordinatorConfig`, `HelperConfig`, `HostAPIConfig`, `RecoveryConfig`, `DeploymentProfile`, `Resource`, `OwnerRequest` and `OwnerResult` are also readable in their source models. Unknown fields, ambiguous JSON and wrong protocol versions are rejected. Config and referenced public HTTPS server/signer files are fingerprinted; changed configuration blocks operations until an explicit reviewed restart/reconciliation. Provision and maintain clock synchronization, set `clock_healthy` from trusted operational evidence, and do not set it speculatively.

Application Owners must use matching SDK contracts. `Observation` no longer
accepts the removed import-evidence field, and plans no longer accept the import
action. This source change does not repin other application repositories or
convert an existing Owner/control database.

## Processes and privilege

| Entry point | Fixed responsibility |
| --- | --- |
| `flamoris-updater serve --config <absolute-config>` | Unprivileged coordinator, dedicated Web and MCP |
| `flamoris-updater-helper --config <absolute-config>` | Root, fixed allowlisted local effects; private peer-checked Unix socket |
| `flamoris-updater-host --config <absolute-config>` | Separate unprivileged loopback host API forwarding signed requests to helper |
| `flamoris-updater-recovery ...` | Independently installed local operator recovery controller |
| `flamoris-update-migration --factory-module <installed-module>` | Application-owned standalone migration factory; request JSON on stdin |

Use audited service units with deployment-specific user/group/path bindings. This repository cannot provide correct production units without that inventory. The helper socket directory is root-owned and configured group-accessible; only `allowed_peer_uids` can dispatch. Host HTTP bodies and framed helper packets are bounded. Bind server TLS directly or use the explicit trusted loopback TLS proxy option for the coordinator; do not expose plaintext coordinator listeners remotely. Serve Web from its dedicated same origin.

Application Owner connections use peer-checked local Unix sockets; their server configuration is also exported as `ServerConfiguration`.

The **application owner API must remain available when the application unit/container is stopped**. Run it as an independent lifecycle owner, not as a route in the unit being updated. It verifies fresh inspection nonces/timestamps, actual schemas/resource identities, durable admission gates, drain/fencing, snapshots, isolated restore and domain acceptance. Production writes, notifications, billing/provider credentials and queues must stay inaccessible during isolated restore. Application-specific proof implementations and Server/GPU Manager integration remain owner integration work.

Native execution checks the configured unit file digest and systemd FragmentPath/NeedDaemonReload, stages a verified read-only indexed tree, changes a fixed pointer and starts under maintenance. Docker uses the protected configured local daemon socket, pinned registry/repository/platform/config/layers, fixed non-root user/network/mounts, resource limits and restart policy. Image-declared anonymous volumes are rejected and image healthchecks disabled. v1 direct OCI fetching uses ordinary system-trusted HTTPS; external bearer-token registry negotiation is not implemented. No host source build or arbitrary shell is allowed.

## Human and MCP authorization

Stop the coordinator before offline account changes; its process lock prevents competing administrative writes. Provision an operator with a prompted password of at least 12 characters and the required exact deployment IDs:

```bash
flamoris-updater provision-user --config /absolute/coordinator.json --subject operator --roles read,plan,execute,cancel,recover_verify,operator,recover --targets app,updater
flamoris-updater issue-token --config /absolute/coordinator.json --subject operator --output /absolute/new-private-token
flamoris-updater serve --config /absolute/coordinator.json
```

Replace the sample paths/IDs with audited bindings. Token output must be a new absolute path; it is written privately. The Web login uses these independent Updater accounts. Changed principal revisions invalidate old session/grant permissions; re-provisioning an account requires a reviewed offline operation. Offline `disable-user --config ... --subject ...` immediately removes that principal’s permissions; `revoke-token --config ... --subject ... --token-file ...` revokes the exact stored token. Both require the coordinator process lock and preserve history. Avoid exporting raw token values in logs or terminal history.

Web provides inventory, candidates, cumulative release notes, update/install planning, exact-plan authorization, execution, progress, history and cancellation. The MCP endpoint is **`/mcp`**, Streamable HTTP with Bearer authentication. Twelve typed tools use the same coordinator as `/api/v1/tools/<tool>`; current schemas come from `inputs.TOOLS` and schema export. The protected local recovery CLI is the mutating recovery route; normal adapters cannot switch protected control roles.

CLI can call the same ordinary HTTPS API with a private Bearer token file, without a client certificate. A literal loopback HTTP URL is also accepted for local/tunneled CLI connections:

```bash
flamoris-updater call --url https://updater.example.invalid --token-file /absolute/token --tool updater_update_plan --arguments /absolute/plan-request.json
```

For a loopback/tunneled CLI connection, replace `--url` with its local HTTP address and add `--public-origin https://updater.example.invalid` matching `CoordinatorConfig.public_origin`; the Host boundary stays enforced.

Use the actual tool names shown by `flamoris-updater call --help` (the `updater_*` names in the exported schema are authoritative). A plan request specifies exact target Manifest digests and a stable request key. Review the returned plan/digest, call `grant` with `caller_id`, `plan_id`, `plan_digest`, then `updater_update_execute` with that authorization ID and a stable execution key. Query `updater_job_get` after a lost reply; one consumed plan cannot create another Job. Do not automatically create a fresh plan to work around unknown effects.

## Independent inspection and recovery

These read-only commands do not bootstrap or migrate the journal:

```bash
flamoris-updater-recovery inspect --state /absolute/coordinator-state
flamoris-updater-recovery compatible --state /absolute/coordinator-state
```

Inspection reports current epoch/mode, claims, unsettled operations, bounded protected-operation summaries, counts and event/export integrity/lag. Inspect both coordinator and relevant host journals. Preserve `journal.sqlite` with its WAL and the independently readable `recovery.jsonl`; do not restore an old control DB, clear blockers, rewrite tombstones or rely on export lag as proof of no effects.

For an unknown parent Job, reconcile actual owners first. Prepare a protected recovery plan:

```bash
flamoris-updater-recovery recover --config /absolute/recovery.json --operator operator --parent-job job-id --targets-file /absolute/previous-targets.json --request-key recovery-key
```

The first call gates/stops the coordinator, hands over authority and positively freezes the complete parent scope. It returns a reviewable plan and does not restore data. The second call with the **same arguments** plus `--approve-plan-digest sha256:<exact-returned-hash>` authorizes that plan. Restore targets must exactly equal recorded pre-update executables; verified original parent snapshots are required. Partial takeover, unknown owner state, missing ACKs or lost uncertain control effects leave the domain inactive/blocked. A `verify` command follows the same review process but retains parent ownership/blockers and does not restore. Read-only verification is not resolution.

Successful linked restore verifies actual final inventory and all local receipts before one global transaction resolves the parent, publishes inventory and releases claims. A retry after a crash at final publication rechecks current authority/inventory and finishes that transaction without replaying application effects. Ordinary interrupted effects remain unknown. After confirmed resolution, `resume-coordinator --config ... --operator ... --request-key ...` starts the accepted coordinator under maintenance, checks readiness and reopens its domain. Retained host claims can block this conservative v1 resume path; do not clear them to bypass recovery.

## Coordinator self-update

Use `self-update --config ... --operator ... --target-manifest sha256:<trusted-root> --request-key ...` to prepare, then the same command with `--approve-plan-digest` to authorize. The stable controller requires an idle domain, current operator/recover scope/revision, exact policy/epoch/previous target and expiry. It stages/probes the candidate with the configured protected Python 3.12 interpreter, advances every host's authority epoch, switches and checks candidate version/epoch/journal readiness under maintenance before activation.

Only control-store/journal/recovery format 1 and schema `{ "control": "updater-control-1" }` are supported. Startup/control-store migrations are prohibited during handoff. Current accounts, sessions, grants/revocations, request/operation tombstones and accepted inventory are preserved. A failed switch/readiness can restore the compatible known previous coordinator using another epoch; it never restores older auth/history state. A failed stage or uncertain handoff has a durable unknown self Job and is not replayed. Accepted coordinator identity is durable, overriding an older bootstrap config on later recovery.

**Root helper/executor and the stable recovery-controller cannot replace themselves through this route.** They require a separate audited bootstrap maintenance/replacement procedure retaining stable inspection/authority paths; protected executor aliases are rejected. This is an explicit v1 blocker, not an unattended rolling upgrade guarantee.

## Build and sign releases

CI builds wheel/sdist/schemas and indexed Native bundles for amd64/arm64 using `requirements-runtime.lock` and binary wheel dependencies. Bundles carry exact file indexes, compatibility metadata, static assets and dependency/license metadata. `verify_bundle.py` uses the production stager and launches all five CLI `--help` paths. Build artifacts are test evidence, not automatically trusted releases.

The manual `sign-release.yml` workflow requires main, an immutable matching `v<version>` tag, protected **release-signing** Environment, approved `RELEASE_ORIGIN`/`RELEASE_KEY_ID` and `UPDATER_RELEASE_PRIVATE_KEY_BASE64`. It builds and verifies both platforms, prepares one exact Manifest with `artifact_variants`, signs exact bytes in the isolated signing job and uploads a reviewable candidate. It has read-only repository contents permissions and **does not publish a release or catalog**. No tag/key/Environment has been created by implementation work.

Release owners review/publish the candidate at the approved origin, sign a monotonically increasing fresh catalog using a **separate catalog key**, and provision trust before managed update execution. The standalone `scripts/sign_release.py --help` supports exact release/catalog signing. A catalog maps one immutable application/release to one signed root; artifact platform selection never substitutes that root identity. Signature rotation may replace a valid signature on identical catalog bytes without changing sequence or release mapping. Existing release history remains readable when eligibility is withdrawn, but revoked signature keys invalidate trust.

Application release packaging, application schema migrations and real systemd/Docker/local-IPC/tunnel/failure acceptance remain A1/A2/D1 in [integration](ADOPTION.md) and [acceptance](ACCEPTANCE.md).
