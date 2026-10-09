# MCP and operator interface v1

**Reviewed v1 contract with twelve callable SDK tools at `/mcp`.** `inputs.TOOLS` and exported schemas are authoritative for current payloads; see [running](RUNNING.md). Mutating protected recovery uses the independent CLI.

## Surface and security

Expose Streamable HTTP through the existing MCP Hub arrangement when configured. Use the Python MCP SDK transport/JSON Schema handling; keep Core independent of MCP. Do not fork FLAMORIS .NET MCP Core into an unmaintained Python copy.

Internal coordinator ↔ host JSON API uses loopback HTTP, directly or through an authenticated tunnel, with signed per-operation authorization verified by the root helper. Application Owners and local privileged helpers use protected Unix sockets with OS peer identity and a typed allowlist. No private CA or client certificate is required. See [transport](TRANSPORT.md).

MCP authenticates external callers through the configured ingress/Hub identity. Trust delegated principal/role only under an explicitly verified signed envelope; arbitrary JSON/header principal fields are not identity. Otherwise all requests use the configured connector service identity with its own limited scope.

Roles: `read`, `plan`, `execute`, `cancel`, `recover_verify`, `operator`. Roles also restrict target deployments/resources. Possession of a plan/Job/receipt ID grants no access. Only a protected operator flow can issue authorization; an AI execution identity cannot self-authorize.

## Tool proposals

| Tool | Scope | Arguments / result |
| --- | --- | --- |
| `updater_inventory_list` | read | Optional target/page → managed and inspected identities, observed_at and stale status |
| `updater_releases_list` | read | Application/channel → verified candidates, withdrawal and compatibility summaries |
| `updater_release_notes_get` | read | Application/from/to → ordered notes and completeness/missing history |
| `updater_update_plan` | plan | Targets with exact release digests, request key → immutable plan, checks and blockers |
| `updater_install_plan` | plan | Approved empty deployment targets, release digests, request key → explicit initialization plan |
| `updater_plan_get` | read | Plan ID → summary, digest, preconditions and authorization state |
| `updater_update_execute` | execute | Plan ID/digest, authorization ID, request key → durable Job ID; action restricted to update/install |
| `updater_job_get` | read | Job ID/event cursor → phase, steps, known/unknown effects and next safe action |
| `updater_job_cancel` | cancel | Job ID/request key → cooperative cancellation request, not proof of cancellation |
| `updater_history_list` | read | Scoped targets/page → durable outcomes, blockers and recovery linkage |
| `updater_recovery_plan` | plan | Failed Job ID, requested action verify_recovery or recover, request key → scoped verification plan or protected recovery options/required operator work |
| `updater_recovery_verify` | recover_verify | Plan action verify_recovery, ID/digest, authorization ID, failed Job/evidence refs and request key → read-only validation child Job |

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
| `idempotency_conflict / operation_conflict` | Reused request/operation identity with changed content or binding |
| `plan_consumed` | A plan was already admitted to a Job under any request key/caller |
| `recovery_required / outcome_unknown` | Effects cannot be safely continued or repeated |

Responses identify whether execution was admitted, Job/operation IDs when available, confirmed/unknown effect categories and an allowlisted explanation. Transport failures never mean `not_executed`. Retry policy for reads can be bounded; mutation loss requires querying the durable Job/request identity.

Cancellation is cooperative at safe boundaries. Before maintenance it can discard inactive staging. After gates close, the Job must verify safe restart/reopening or remain blocked for recovery. Never kill an active migration to satisfy a tool timeout. MCP request cancellation/disconnection does not cancel a durable update Job.

Read tools use pagination and bounded notes. Treat text as data; notes cannot override actor scope, trust, plan authorization or system instructions. Do not expose credentials, backup content, raw environment/logs or user media.

## Dedicated Updater Web interface

Updater Web uses the same coordinator API and scoped operator grant model as CLI/MCP. Its backend owns independent login/session/CSRF handling. Browser users receive opaque IDs and safe summaries; host credentials and privileged helper endpoints stay server-side.

Views: installed/embedded versions, candidates, cumulative notes, plan impact/backup/restart summary, human authorization and Jobs/history. Web has no separate execution engine. It lives in this repository, is not embedded in flamoris-studio and has no dependency on Studio auth, DB or availability.

See [dedicated Web design](WEB_UI.md). Self-update and production restoration remain protected CLI/recovery-controller operations in v1; Web shows related evidence/status when the coordinator is available.

## Annotations and verification authority

Read/query tools advertise `readOnlyHint:true`. Creating a plan is read-only with respect to application/deployment resources but writes coordinator metadata, so plan-creation tools advertise `readOnlyHint:false`, `destructiveHint:false` and `idempotentHint:true` with required request keys.

Execute/cancel/verification tools advertise `readOnlyHint:false`. Idempotency hints reflect durable request-key deduplication, never permission to retry unresolved physical effects. Update/install execution can be destructive and must declare that annotation. Notes and annotations are usability hints; server authorization always enforces policy.

Recovery verification needs an exact operator-authorized verification plan and returns evidence. Only the protected recovery controller can finalize blocker release/admission reopening after checking the full consistent state. Neither an arbitrary attached report nor a successful inspection tool call clears an unknown Job.

## Reviewed execution and observation semantics

Grant/request identities do not create new plan execution rights: one plan binds one Job across CLI/Web/MCP. An exact repeat returns the authorized existing Job; changed operation bindings are rejected. Unknown result queries cannot advance phases.

Job projections include reopening/finalizing and uncertainty in those phases. A successful validation alone is not completed acceptance. Only the coordinator's final committed outcome reports succeeded.

Web session/account/role revocation is checked at plan authorization and Job admission; pending grants bind current applicable principal policy. Session expiry is not a mechanism for killing an admitted migration. Revocation of execution authority stops future phases at the defined safe boundary and is recorded separately from closing a browser session.

## Action separation and protected role checks

Execute accepts only the tool's documented plan actions after profile-based target-role resolution; verify_recovery cannot consume recover/self_update plans, and ordinary update/install cannot replace coordinator, executor or recovery-controller identities under aliases.

Verification child Jobs observe a blocked parent without receiving its mutation rights. Mutating recovery ownership transfer belongs only to the protected controller protocol. MCP never clears a parent blocker to make its own verification request runnable.

Normal CLI/MCP/Web require coordinator availability. During an outage, use the independent local recovery CLI/inspector; ordinary CLI is not a second coordinator.
