> Historical design/integration record. The current simple flow is in [running](RUNNING.md) and [installation](INSTALL.md). Backup/restore, unmanaged import and client PKI requirements/examples below are superseded and are not accepted current contracts. Publication/full-host acceptance do not gate controlled installation tests.

# Design acceptance matrix

**Acceptance criteria with partial automated source coverage; live certification pending.** The original design task executed no runtime tests. The later implementation adds regression/protocol/artifact/recovery tests listed in [implementation review](IMPLEMENTATION_REVIEW.md) and [PROGRESS](../PROGRESS.md). Rows below remain requirements until their owning live acceptance is evidenced.

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
| Unmanaged or unsupported application version | Reject managed update; no import or conversion path |
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
| Web disconnected during Updater self-update | Independent recovery CLI/controller handoff continues; reconnect reads persisted evidence |
| Consumed plan with another caller/grant/adapter/request key | At most one Job; return an authorized existing identity or plan_consumed; preserve tombstone after failure/cancel |
| Same operation ID with changed action/input/resource/epoch/predecessor | operation_conflict before effects; exact duplicate only queries persisted state |
| Activation request before backup/group barrier receipts | Reject step admission; an authenticated coordinator cannot skip prerequisites |
| Candidate restart, timer or administrative writer during maintenance | Durable owner epoch still gates new work; no automatic migration/replay |
| Health passed but reopening/local release/global commit is incomplete | No succeeded claim or conflicting Job admission; reconcile recorded finalization |
| Safe failure/cancel with missing local reservation-release evidence | Remain blocked/unknown until local receipts and global terminal commit; never infer safety from an exception |
| Two host aliases address one DB, including standalone runner | One authoritative physical-resource owner/fence; no independent local-lock migration |
| Runner outcome enum inconsistent with operation type | Reject invalid receipt; reconcile accepts applied_verified while inspection cannot authorize apply |
| Identical catalog sequence/digest fetched repeatedly | Accept unchanged evidence; equal-sequence changed digest and lower sequence are rejected |
| Staged Native runner modified or writable loader path selected | Reject before execution/rollback; recheck sealed identity and trusted environment |
| Oversized catalog/notes, duplicate mapping or escaping locator | Enforce streaming/parser/response budgets and confinement; paginate history |
| Scratch restore validator attempts production credentials, timers or network effects | No production access/effects; unsupported isolated verification blocks update |
| Removed entry command, registration tools/action/role or evidence field | Not packaged/listed; reject before a Job or physical effect |
| Self rollback with newer auth/grant/trust/consumption state | Preserve all current control records and monotonic watermarks; no destructive routine store migration |
| Recovery verify receives recover/self_update plan or runs over unsettled parent effects | Reject wrong action; return unknown for unstable observation; never acquire mutation rights or clear blockers |
| Protected recovery interrupted during parent-to-child ownership transfer | No concurrent rights or parent resume; partial handoff stays blocked and is reconciled |
| Unchanged incoming client or unrelated matching provider instance | Resolve exact deployment bindings; verify full affected graph and disclose additional scope before authorization |
| Coordinator/executor target disguised as ordinary application alias | Resolve protected local role and reject normal Web/CLI/MCP update/install |
| Old coordinator after partial epoch handoff or executable rollback | Reject stale-epoch mutation; all managed host acknowledgements required; rollback uses a newer epoch |
| Coordinator outage while operator uses ordinary CLI | Ordinary interfaces unavailable; independent recovery CLI can inspect and only perform protected authorized recovery |
| Recovery planning repeated with a request key or changed requested action | Shared plan-creation deduplication; changed payload conflicts; verify_recovery/recover remain distinct |

## Review and release gates

Documentation review verifies ownership, entry versions, protocol consistency, example shape, relative links and explicit source/release/live status.

Implementation acceptance uses fake providers, isolated DB/resources and crash/duplicate/fault injection. Live managed updates require actual deployment/artifact/schema/writer inventory and scoped restore/lifecycle validation.

No review checklist or green source CI alone declares a signed release, migration, deployed health or live production acceptance complete.
