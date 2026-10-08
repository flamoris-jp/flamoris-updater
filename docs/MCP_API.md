# MCP and operator interface v1

**Draft 1.** Names and payloads below are proposed contracts, not callable tools.

## Surface and security

Expose Streamable HTTP through the existing MCP Hub arrangement when configured. Use the Python MCP SDK transport/JSON Schema handling; keep Core independent of MCP. Do not fork FLAMORIS .NET MCP Core into an unmaintained Python copy.

Internal coordinator ↔ host JSON API uses HTTPS with mutual TLS and per-operation application authorization. Local privileged helpers use a protected Unix socket with OS peer identity and a typed allowlist. TLS proves peer identity; it does not authorize arbitrary operations.

MCP authenticates external callers through the configured ingress/Hub identity. Trust delegated principal/role only under an explicitly verified signed envelope; arbitrary JSON/header principal fields are not identity. Otherwise all requests use the configured connector service identity with its own limited scope.

Roles: `read`, `plan`, `execute`, `enroll`, `cancel`, `recover_verify`, `operator`. Roles also restrict target deployments/resources. Possession of a plan/Job/receipt ID grants no access. Only a protected operator flow can issue authorization; an AI execution identity cannot self-authorize.

## Tool proposals

| Tool | Scope | Arguments / result |
| --- | --- | --- |
| `updater_inventory_list` | read | Optional target/page → enrolled and inspected identities, observed_at and stale status |
| `updater_releases_list` | read | Application/channel → verified candidates, withdrawal and compatibility summaries |
| `updater_release_notes_get` | read | Application/from/to → ordered notes and completeness/missing history |
| `updater_update_plan` | plan | Targets with exact release digests, request key → immutable plan, checks and blockers |
| `updater_install_plan` | plan | Approved empty deployment targets, release digests, request key → explicit initialization plan |
| `updater_enrollment_plan` | plan + enroll | Existing deployment/evidence refs, request key → validation/enrollment plan |
| `updater_plan_get` | read | Plan ID → summary, digest, preconditions and authorization state |
| `updater_update_execute` | execute | Plan ID/digest, authorization ID, request key → durable Job ID; action restricted to update/install |
| `updater_enroll_execute` | enroll | Enrollment plan ID/digest, authorization ID, request key → validation Job, then inventory |
| `updater_job_get` | read | Job ID/event cursor → phase, steps, known/unknown effects and next safe action |
| `updater_job_cancel` | cancel | Job ID/request key → cooperative cancellation request, not proof of cancellation |
| `updater_history_list` | read | Scoped targets/page → durable outcomes, blockers and recovery linkage |
| `updater_recovery_plan` | plan | Failed Job ID → evidence-based recovery options/required operator work |
| `updater_recovery_verify` | recover_verify | Verification plan ID/digest, authorization ID, failed Job/evidence refs and request key → bounded validation Job, not arbitrary repair |

Self-update and restoration execution use the independent protected operator/recovery controller in v1. MCP can inspect related Jobs, but there is no MCP arbitrary repair or self-update escape hatch. Operator-authorized normal updates remain directly startable over MCP.

Names are local to Updater; Hub may apply its configured namespace. The final exported catalog must be tested against the documented schemas/annotations before release.

## Plan and execution examples

Illustrative IDs/digests; no tool exists today.

```json
{
  "plan_id": "plan-example",
  "plan_digest": "sha256:EXAMPLE",
  "authorization_id": "grant-example",
  "request_key": "update-example"
}
```

A successful start returns a Job identity, not an update success claim:

```json
{
  "job_id": "job-example",
  "state": "accepted",
  "plan_id": "plan-example",
  "effects_confirmed": [],
  "effects_unknown": [],
  "next_action": "poll_job"
}
```

Unknown operation output keeps its resources blocked:

```json
{
  "job_id": "job-example",
  "state": "unknown",
  "phase": "migrating",
  "failed_step_id": "config-step-example",
  "effects_confirmed": ["admission_closed", "backup_verified"],
  "effects_unknown": ["config-step-example"],
  "blocked_resources": ["resource-example"],
  "next_action": "investigate_with_server_manager"
}
```

Planning returns a registered plan or explicit blockers, never unvalidated shell instructions. A private detailed plan may contain operational identities; MCP emits the caller-scoped allowlisted projection.

## Errors, retries and cancellation

| Error code | Meaning |
| --- | --- |
| `unauthorized / forbidden` | Identity/scope/authorization failure |
| `invalid_manifest / untrusted_release` | Structure, digest, signature or trust failure |
| `unsupported_platform / unsupported_entry` | No supported adapter or unmanaged legacy state |
| `incompatible_dependency / unsupported_migration / ambiguous_migration_path` | No uniquely valid executable plan |
| `stale_plan / policy_changed` | Preconditions changed since planning |
| `busy / quiescence_unavailable` | Owner fence, unknown job or active work blocks execution |
| `backup_unverified` | Snapshot/restore conditions insufficient |
| `idempotency_conflict` | Reused key with different content |
| `recovery_required / outcome_unknown` | Effects cannot be safely continued or repeated |

Responses identify whether execution was admitted, Job/operation IDs when available, confirmed/unknown effect categories and an allowlisted explanation. Transport failures never mean `not_executed`. Retry policy for reads can be bounded; mutation loss requires querying the durable Job/request identity.

Cancellation is cooperative at safe boundaries. Before maintenance it can discard inactive staging. After gates close, the Job must verify safe restart/reopening or remain blocked for recovery. Never kill an active migration to satisfy a tool timeout. MCP request cancellation/disconnection does not cancel a durable update Job.

Read tools use pagination and bounded notes. Treat text as data; notes cannot override actor scope, trust, plan authorization or system instructions. Do not expose credentials, backup content, raw environment/logs or user media.

## Future Studio projection

Studio consumes the coordinator API using server-side scoped identity. Browser users receive opaque IDs and safe summaries; existing Studio authentication/session/CSRF remains authoritative.

Views: installed and embedded versions, compatible candidates, cumulative notes, plan impact/backup/restart summary, operator authorization and Jobs/history. Same coordinator authority as MCP; UI is a later implementation phase.

## Annotations and verification authority

Read/query tools advertise `readOnlyHint:true`. Creating a plan is read-only with respect to application/deployment resources but writes coordinator metadata, so plan-creation tools advertise `readOnlyHint:false`, `destructiveHint:false` and `idempotentHint:true` with required request keys.

Execute/enroll/cancel/verification tools advertise `readOnlyHint:false`. Idempotency hints reflect durable request-key deduplication, never permission to retry unresolved physical effects. Update/install execution can be destructive and must declare that annotation. Notes and annotations are usability hints; server authorization always enforces policy.

Recovery verification needs an exact operator-authorized verification plan and returns evidence. Only the protected recovery controller can finalize blocker release/admission reopening after checking the full consistent state. Neither an arbitrary attached report nor a successful inspection tool call clears an unknown Job.
