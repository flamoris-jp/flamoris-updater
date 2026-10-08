# Design acceptance matrix

**Future tests and live acceptance criteria; no tests executed by this design task.**

| Case | Expected evidence / outcome |
| --- | --- |
| Manifest duplicate/unknown fields, bad types or unsupported version | Reject before plan admission |
| Signature/digest mismatch or wrong application-scoped key | Untrusted release; no lifecycle/data effect |
| Catalog rollback, expiry, withdrawal or conflicting digest for same release | Reject candidate/admission; retain published history |
| New catalog confirms unchanged admitted target | Accept fresh evidence without broadening the plan |
| Wrong OCI platform, unsafe Native archive or exceeded quota | Staging rejected without active-tree writes |
| No schema change | Domain validation; no migration side effects |
| Direct schema 1 → 3 with withdrawn release 2 | Target-bundled route; no intermediate installation |
| Incompatible schema vector or ambiguous routes | Block plan; no arbitrary route selection |
| Unsupported application entry version | Standalone transition required; no silent enrollment |
| Source/package/tag/component version disagreement | Explicit mapping; no guessed installed release |
| Existing or unreadable resource during install | Refuse initialization |
| Shared DB with unknown writer | Refuse migration/restore until owner fencing verified |
| Idle observation without maintenance fence | Block mutation despite apparent idle state |
| Active/unknown Generation or inference job | Preserve debt, refuse update and request reconciliation |
| Snapshot created but isolated restore failed | Block migration; never report backup verified |
| Same request key repeated/lost start response | One admitted Job; query persisted identity |
| Same request key changed payload | Idempotency conflict |
| Crash before/after transactional migration commit | Verified not-applied or applied result; never automatic replay of unknown |
| Partial DB/file migration or lost result | Persistent blocked resources and recovery_required/unknown |
| Disk full or journal/export failure | Stop before new destructive effects |
| Stale plan, changed secret reference/profile or revoked grant | Reject before admission or stop later phase at safe boundary |
| MCP caller supplies command/path/role or another user's Job ID | Reject by strict schema and actor/target scope |
| MCP disconnects or times out | Durable Job survives; no inferred cancellation |
| Cooperative cancel before/after maintenance | Confirm safe restored lifecycle or retain recovery blockers |
| Host lost during coordinated activation | No split retry/lease-expiry takeover; preserve local evidence |
| Mixed-version group or partial gate reopen fails | Gates/accepted work reconciled; no independent DB rollback |
| Old binary incompatible with new data | Artifact-only rollback rejected |
| Restore would discard new writes or replay external effects | Restoration rejected pending owner-approved recovery |
| Model refetch unavailable or asset uniquely modified | Preserve asset explicitly; do not exclude it from recovery |
| New Updater cannot read stable journal | Maintenance-only handoff fails; independent compatible pointer recovery |
| Self rollback with newer application operations | Never overwrite journal; reconcile and preserve tombstones |
| Missing release history vs missing target notes | Mark cumulative notes incomplete vs reject target metadata |
| Basic health vs billable/domain validation | Distinct evidence; no unauthorized paid/provider call |
| Dedicated Web while Studio is stopped | Operator screen works through Updater; no Studio auth/DB dependency |
| Web/CLI/MCP observe the same admitted update | One coordinator/Job history; scopes enforced on every adapter |
| Web authorization or mutation lacks session/CSRF/scope | Reject before grant or effect admission |
| Browser refresh/lost start response | Query/reuse existing request identity; no duplicate Job |
| Web disconnected during Updater self-update | CLI/controller handoff continues; reconnect reads persisted evidence |

## Review and release gates

Documentation review verifies ownership, entry versions, protocol consistency, example shape, relative links and explicit draft/unimplemented status.

Implementation acceptance uses fake providers, isolated DB/resources and crash/duplicate/fault injection. Live enrollment requires actual deployment/artifact/schema/writer inventory and scoped restore/lifecycle validation.

No review checklist or green source CI alone declares a signed release, migration, deployed health or live production acceptance complete.
