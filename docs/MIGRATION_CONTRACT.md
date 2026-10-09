# Application migration contract v1

**Reviewed v1 contract; common runner implemented.** Application-specific handlers remain owning-repository work. Actual contracts/models and [running](RUNNING.md) define executable fields.

## Resource identity and schemas

A host profile maps logical resources (`config`, `database`, `persistent-data`) to stable `resource_id` values and writer sets. Resource identity includes DB namespace/schema or file namespace, not just a path label. Shared resources have one schema owner and one backup/restore domain.

Schema observations return `resource_id`, owner, actual schema ID, protected config/mapping revision, domain journal revision, active/unknown work and inspect evidence ID. Profiles resolve physical identity and a single authoritative resource owner: two host/path/DB aliases for the same namespace must map to the same resource and consistency domain. A remote/shared DB migration must acquire its owner-maintenance fence, not only the caller host's local lock. Unknown, unreadable or conflicting state rejects planning. Rows may change during normal operation; do not hash an entire mutable DB to make every plan instantly stale. Plan preconditions bind schema/ownership/config revisions and the drain contract; snapshot contents are bound later after quiescence.

For shared DBs, register all participating writers, migration-role authority and restore coupling. Unknown external writers block destructive migration until fenced or positively excluded. A handler cannot declare exclusive ownership just because its application is stopping.

## Planning a transition graph

Each edge names source/target schema maps, required schemas for untouched resources, affected resources, handler/reconcile IDs, bounded runner profile, retry policy, backup and recovery conditions.

Construct the graph over the full relevant schema vector. An edge is eligible only when its `from` and `requires` match the current vector; apply `to` without changing undeclared resources. This prevents independently planned config/DB migrations from producing an unsupported pair.

Find a path entirely supplied by the selected trusted target artifact, within host policy and the approved destructive-change scope. Exclude edges without supported backup/restore/validation. Prefer the unique shortest supported path; equally short alternatives return `ambiguous_migration_path` unless the signed release explicitly names a validated preferred route. Do not pick lexicographically or download/install intermediate release binaries.

A route may be schema 1 → 3 even if release 2 was withdrawn. Schema versions are opaque IDs; numbers in this example only illustrate the graph. No path is needed when the whole target vector already matches.

Cycle-containing definitions, conflicting edges and excessive graph size are rejected. Define explicit no-op validation when schemas match; no migration handler is silently invoked.

## Runner protocol

The future runner accepts bounded JSON and emits bounded schema-validated JSON. Host profile selects invocation and maximum duration; no shell interpolation is allowed.

| Operation | Inputs | Output / behavior |
| --- | --- | --- |
| `inspect` | Resource bindings resolved by executor | Actual schemas, writer/active-work status and evidence |
| `plan` | Target digest, observed vector and local policy | Ordered handlers, preconditions and recovery requirements; no data writes |
| `apply_step` | Stable operation ID, expected schemas, exclusive-resource receipt, verified backup receipt | Verified result plus resulting schemas or explicit failure/unknown |
| `reconcile` | Operation ID and persisted intent | `not_applied|applied_verified|partial_known|unknown` plus evidence |
| `validate` | Expected target vector | Domain invariants, schema and data/permission preservation results |
| `initialize` | Explicit empty-state proof and install authorization | New resources and verified target vector |

No operator-supplied module, script path or DB connection string is accepted. Secret credentials are delivered directly to the isolated runner by the host's protected profile. Runner stdout/stderr is not published raw through MCP.

## Journals and at-most-once admission

Host records durable intent before calling a handler. Application records durable intent before application effects, then its outcome and verified actual schemas. They share the same operation ID but are separate authorities; there is no pretend cross-journal transaction.

A transactional DB handler can commit schema/data changes and its application result together. For file and cross-resource work, stage writes and explicitly record bounded substages/checkpoints with reconciliation. Never claim atomicity across DB/files.

A lost response or crash after intent results in an unknown host outcome until application reconciliation verifies the actual result. A schema marker alone does not prove the step finished.

| Reconcile result | Coordinator action |
| --- | --- |
| `not_applied` | Record evidence; a fresh plan/authorization may retry only if declared safe |
| `applied_verified` | Adopt verified result for the same operation; never call it again |
| `partial_known` | Keep resources blocked; generate a supported recovery plan |
| `unknown` | Keep resources blocked; human + AI investigation |

Even an idempotent handler is not automatically replayed after an unknown result. Application run/step uniqueness and local admission receipts prevent duplicate accepted operations; they do not imply exactly-once distributed side effects.

Update records are append-only at the logical level; correction adds reconciliation evidence rather than rewriting prior failure into success.

## Quiescence and role separation

Close application admission first, wait for already accepted work to finish and verify no pending unknown provider effects. Stop/fence every registered writer, including timers and administrative import/retention paths, before the snapshot and migration.

Acquire an application-provided durable maintenance epoch/fence held through validation/reopening. Candidate startup and restarted timers must honor it before domain writes; an old process lock disappearing cannot clear maintenance. Mere observation that an application is idle is insufficient. Generation currently has one reservation/owner authority, and GPU Node Manager already has its own lock; adapters must use their owners' supported maintenance contracts. Missing contracts are implementation blockers, not permission to kill processes.

DB migration credentials differ from runtime DML credentials. Backup and restore roles are narrowly scoped. Existing owners, ACLs, grants and protected data are validation invariants.

## Application-owned schema migration

The independent runner remains available for normal schema changes through pinned
application-owned handlers. It does not convert unmanaged deployments into
Updater-managed installations. There are no entry-transition receipts or
registration operations. Schema migration must not be confused with installing
an old release before the target release.

## Acceptance scenarios

Test unchanged schemas, direct 1 → 3, unsupported intermediate vector, ambiguous route, concurrent writer, active/unknown provider job, transactional crash before/after commit, partial file publication, duplicate operation, lost response and unsupported rollback. Exercise existing SQL/Alembic ID mapping without erasing history or converting unknown data into empty state.

## Request/result envelope

Every request names `contract_version:1`, operation, application/deployment IDs, immutable artifact digest, operation ID and profile-resolved resource IDs. Apply additionally requires expected schema vector and owner-validated maintenance/backup receipt IDs. Unknown fields/types fail validation.

Results name the same version/identities/operation ID, operation-specific outcome, observed schemas and bounded evidence refs. Inspect/plan/validate use `verified|unknown`; apply_step/initialize use `applied_verified|not_applied|partial_known|unknown`; reconcile uses `not_applied|applied_verified|partial_known|unknown`. `verified` and `applied_verified` are distinct valid values with those exact operation restrictions. Exit status, response envelope and persisted domain result must agree. A zero process exit or response missing evidence is not a successful migration. An inspection/plan response cannot be used as an apply receipt.

A runner timeout requests cooperative termination only where the declared handler supports it. Otherwise fence resources and record unknown while reconciling the process/domain journal. Do not kill a nontransactional handler and immediately restart it.

## Shared resources, immutable operations and snapshot isolation

Standalone tools and coordinator-driven runners honor the same application/resource-owner maintenance contract and immutable operation binding. They cannot bypass another host's active/unknown maintenance ownership with a local-only lock. Resource alias discovery is read/validation work; uncertain ownership blocks planning rather than inventing a second owner.

Apply requests bind the exact handler/input/artifact/schema/resource/maintenance epoch and backup/predecessor receipts. Same operation ID with changed binding is rejected even if a caller labels the handler idempotent.

A restoration drill is not ordinary candidate startup. The backup owner supplies a profile-confined scratch namespace, scratch credentials and read/validation-only invocation. Block production DB/resource mounts, production secret identities, provider/network side effects, timers, automatic migration and job replay. Production write credentials are never handed to the scratch validator. If the owner's schema/grant/content checks cannot run with these constraints, restoration verification is unsupported and the update is blocked.

## Source clarification

Every physical resource has one registered owner and all known writers. Shared observed/target schemas must agree; only the owner changes/snapshots/restores it. Consumer guards can reference borrowed schemas after the owner's planned transition. Fresh owner inspections echo a nonce/time and report actual physical binding digests. The common standalone runner uses installed allowlisted handlers and durable intent; an unknown committed SQLite transaction is never replayed. Actual application handler and production proof correctness require separate verification.
