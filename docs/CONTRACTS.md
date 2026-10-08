# Contract requirements

**State:** requirements for detailed design. No formal schema, executable manifest, tool catalog or implementation exists yet.

## Release Manifest

A versioned, machine-readable Manifest must describe:

| Area | Required information |
| --- | --- |
| Identity | Application ID, release version, Manifest schema version, immutable source revision |
| Artifact | Docker/Native kind, platform constraints, immutable reference, digest and signature evidence |
| Trust | Binding to artifacts, migration/validation content and release notes under configured trust policy |
| Compatibility | Provided APIs, required dependency IDs/ranges and group constraints |
| Data | Independent config, DB and persistent-data schema versions |
| Migration | Supported source/target schemas, stable edge/step IDs, bundled handler identity and execution requirements |
| Lifecycle | Declared bounded operations, stop/isolation/restart requirements and pre/post validation |
| Recovery | Backup scope, restore verification, preserved artifact and conditions for rollback |
| Configuration | Public config contract, protected secret references and persistent data locations |
| Release notes | Human-readable notes and structured changes/known issues |

The exact syntax and field names remain pending. No YAML example should be treated as a supported schema. Secret values and arbitrary command strings are excluded.

## Application migration contract

Each application supplies inspect, plan, migrate and validate capabilities with bounded inputs and machine-readable outcomes. API names and invocation form are pending.

The contract must support:

- Inspection of actual schemas and data state without mutation.
- Explicit supported directed edges; no inference that adjacent release numbers imply a migration.
- A plan including preconditions, writers to quiesce, required locks and backup/restore evidence.
- Stable step identities and a persistent journal with intent, outcomes and validation evidence.
- An explicit policy for reconciliation, safe retry, partially applied operations and nontransactional steps.
- Verified postconditions and reported resulting schemas.
- Standalone execution for the pre-enrollment transition.

A handler cannot simply mark the target schema before verifying data. DB/config/file updates are not presumed to share one transaction. Unknown state stops execution.

## Enrollment and initialization

Enrollment verifies an already accepted management-entry release, artifact identity, actual schemas, config/data mapping and successful standalone transition evidence. It records the verified inventory without silently rebuilding or migrating a legacy installation.

New installation requires a separate empty-state check and explicit initialization authorization. Existing data, missing markers and inaccessible state are never interpreted as permission to initialize.

## Plan, authorization and jobs

Plans bind immutable release artifacts, target applications/hosts, compatibility results, inspected schemas, operation order, backup/restore requirements and expected preconditions.

Execution requires caller/host authorization for that exact plan. Recheck live preconditions and locks; a stale or altered plan must not execute under earlier approval. Long work returns a durable Job ID. Request deduplication and recovery from a lost response must prevent a second execution.

The journal must expose the failed phase, completed effects, uncertain effects and validation results without secret values. An independently readable format is required for Updater outages.

## MCP capability groups

The following are planned capabilities, **not callable tool names**:

| Group | Access | Result |
| --- | --- | --- |
| Inventory and release discovery | Read | Enrolled versions, compatible candidates and release metadata |
| Release notes | Read | Per-release and cumulative human/structured changes |
| Planning | Read | Validated plan and effects/recovery requirements |
| Execution | Authorized mutation | Start one validated plan and return durable Job ID |
| Progress and history | Read | Job state, step outcomes, validation and unresolved state |

MCP does not grant arbitrary shell access or broaden host permissions. Investigation uses Server Manager and Updater's own records. Exact tool names, error shapes, permission scopes, transport and cancellation semantics remain detailed-design work.

## Validation scenarios for implementation

Acceptance must exercise a direct schema 1 → 3 path with release 2 withdrawn, unchanged schemas across a release update, interrupted migration with unknown outcome, stale plans, duplicate Job starts, signature/digest mismatch, incompatible dependency groups, failed restore verification, existing-data initialization refusal and an Updater self-update failure.

This is a future behavioral acceptance list, not a statement that tests currently exist.
