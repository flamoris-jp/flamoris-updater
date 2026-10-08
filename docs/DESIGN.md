# FLAMORIS Updater design

**State:** accepted basic direction; implementation pending. [Detailed draft 1](DETAILED_DESIGN.md) specifies proposed APIs, persistence, trust and failure semantics.

## 1. Repository and dependency boundaries

Keep reusable Update Core and the FLAMORIS wrapper in `flamoris-updater`. No separate core/native repository is planned.

Core owns portable mechanisms: trusted release verification, dependency and migration-path planning, durable journals, locking, bounded execution coordination and recovery records. It must not embed FLAMORIS service names, machine names, private topology, deployment paths or UI rules.

The wrapper owns the FLAMORIS catalog, deployment profiles, management-entry policy, dependency groups and operating policy. Docker/Native host adapters implement declared lifecycle operations. External MCP and a future UI adapt the same domain authority.

Each application owns its configuration, DB and persistent-data formats, migrations and validators. Core can share migration machinery without owning application-specific transformations.

Server Manager is the primary source for live server status and diagnostics. GPU Node Manager retains runtime/GPU lifecycle and exclusion authority. Updater coordinates through their supported contracts rather than creating parallel state machines.

## 2. Entry into management

| Target | Baseline agreed for transition | Management entry |
| --- | --- | --- |
| Installed AI-side applications | v0.1 | v1.0 |
| GPU Node Manager | v1.1 | v1.2 |
| Updater | New | v1.0 |

The deployed application list and artifact identities must be audited before implementation. These values describe the agreed release boundary, not discovered live state.

Each application provides a standalone transition to its entry version. This transition does not require Updater and adopts the common migration contract. After successful migration and validation, Updater verifies evidence and enrolls the application. It must not infer, rewrite or silently adopt an unknown legacy deployment.

An application release, config schema, DB schema and persistent-data schema are separate version dimensions.

## 3. Update units and compatibility

The default update unit is one application. Use a coordinated group when dependencies require it. Release Manifest declares provided API versions and required dependency compatibility ranges; Core checks the complete selected plan.

Group coordination is not a claim of atomic DB or multi-host rollback. The plan must identify intermediate compatibility, ordering, stop conditions and recovery boundaries. Draft multi-host preparation, gated activation and partial-failure semantics are specified in [execution/recovery](EXECUTION_RECOVERY.md); no distributed rollback guarantee is introduced.

Planning does not mutate application/deployment resources; immutable plans may be persisted in coordinator metadata. Execution uses a reviewed, authorized plan and revalidates its preconditions immediately before mutation.

## 4. Migration graph and execution history

Represent supported schema transitions as directed edges, independently of release numbering. If release 2 is withdrawn, a target release may ship a supported schema 1 → 3 migration. Installed schema 2 still needs its own supported path. If schemas have not changed, a release change may need no migration.

Paths are selected from inspected data schemas and persistent execution history. A claimed release version alone is insufficient.

Each migration step records its start and outcome durably. Successful, failed and unknown/partially applied states remain distinct. Record intent before side effects and verified results afterwards. An interrupted operation is reconciled against actual state; it is never blindly replayed.

Migration handlers and validators ship with the owning application release. Intermediate schemas may be traversed without installing intermediate application binaries when the target ships the required supported handlers.

Stop or isolate affected writers and acquire the required locks before changing data. No automatic retry or reverse migration is assumed safe. Unknown state or disagreement between data and history stops the plan for human + AI investigation.

## 5. Backup and recovery

Cover configuration, databases and persistent application data. Restore verification is required; creating an archive successfully is not proof of recoverability. A plan must associate verified backups and restoration conditions with its actual pre-update state.

Models are normally separately managed, retrievable assets. Record identity, source, digest/license and retrieval requirements. Unique or modified assets that cannot be retrieved must have a preservation policy; do not silently exclude irreplaceable data.

A destructive update cannot proceed automatically when recovery cannot be verified. Restoration must respect cross-application DB dependencies and coordinated snapshots; do not assume restoring one service leaves its peers consistent.

Retain durable update and migration evidence outside replaceable runtime artifacts. Records must remain readable when Updater is unavailable.

Preserve a known executable previous Updater and provide a small independent recovery path for self-update failures. The proposed stable recovery controller and self-update handoff are specified in [execution/recovery](EXECUTION_RECOVERY.md).

## 6. Release distribution and trust

CI builds release artifacts. Hosts normally install prebuilt artifacts rather than building source. Docker images and Native bundles use immutable identities with digests and signatures.

Treat manifests and release notes as untrusted input. Verify against the configured trust policy before mutation, including binding the manifest to the artifact and its migration/validation content. A manifest cannot grant itself trust or permission to execute arbitrary commands.

The [Manifest draft](RELEASE_MANIFEST.md) selects exact-byte Ed25519 signatures, application-scoped operator-pinned keys, catalog replay protection and rotation/revocation rules. Key provisioning and the CI signing pipeline are not implemented.

## 7. Configuration and persistence

| Purpose | Agreed default direction |
| --- | --- |
| Native runtime | `/opt/<application>/`, installed from a release artifact |
| Docker deployment | `/srv/docker/<application>/` |
| FLAMORIS configuration | `/etc/flamoris/<application>/` |
| Secrets | Separate protected store/directory, referenced without values in manifests |
| Persistent application data | `/var/lib/<application>/` or an explicitly retained existing data area |
| Models and generated assets | Separately managed persistent storage, outside replaceable runtime |
| Update/migration history | Dedicated persistent area readable independently of Updater |

These are portable design defaults, not verified live paths. Never clone source directly into `/opt`.

New management-entry releases adopt standard separation. Existing installations move incrementally through application-owned validated transitions. Do not relocate all live configuration at once or copy private host paths into public defaults.

## 8. Host permissions and MCP

Place a least-privilege execution mechanism on each managed host. Updater requests only predefined, authorized operations. A shell string from an MCP caller or manifest is never an operation contract.

Updater MCP focuses on inventory, release discovery/notes, update planning, starting an authorized plan, job progress and update history. Long updates are asynchronous Jobs with durable IDs. The MCP facade must share the same execution authority as other interfaces.

Server observation and general diagnostics remain with Server Manager. Updater reports its own update evidence and failed step. It does not add a read-only shell, a general log service or an independent diagnostic suite.

Authorization binds the exact plan, artifacts, targets and relevant preconditions. Repeated start requests must not duplicate execution. Unknown outcomes require reconciliation rather than unconditional replay.

## 9. Failure handling with human + AI

1. Updater stops safely and records the failed step, confirmed changes and unresolved state.
2. AI reads Updater evidence and obtains current server evidence from Server Manager.
3. Human and AI determine a repair or restoration path.
4. When needed, AI prepares a reviewable recovery script/package for the human to execute.
5. Revalidate live state and record the recovery outcome before permitting another update.

Do not claim that a failed step changed nothing, that a group rolled back atomically or that a repair succeeded without evidence. Recovery exceptions are not a general remote-shell feature of Updater.

## 10. Installation and release notes

New installs and updates use the same release specification. Initialization is an explicit operation separate from migration; unknown or existing data must never be mistaken for an empty installation.

Each application publishes human-readable notes and machine-readable changes with its release. Updater aggregates them, including cumulative changes between installed and target releases, compatibility changes, migrations, restarts, known issues and rollback conditions.

Withdrawn intermediate releases must not be installed just to obtain their notes or migration numbering. Release-note availability and missing history must be explicit.

Studio's future management UI shows installed versions, candidates, plans, release notes and execution outcomes. UI work follows the underlying contracts.

## 11. Detailed design and remaining evidence

[Detailed draft 1](DETAILED_DESIGN.md) chooses platform/language, package/API boundaries, Manifest/trust, migration runner, durable jobs/authorization, group failures, self-update recovery and MCP contracts.

Remaining evidence and owning-application work: exact live inventory and artifact/version mappings, maintenance/drain contracts, DB-role and backup scopes, signing-key provisioning, host bindings, implementation verification and live acceptance. These are not inferred from source inspection. See [adoption](ADOPTION.md).

The draft refines the accepted direction without changing responsibility or management-entry versions. The current task remains design-only.
