# Progress

Updated: 2026-10-08.

## Current state

**Updater-owned v1 source implementation complete; publication and live adoption pending.** The reviewed design was merged in PR #4; implementation and review corrections are tracked in PR #5. This source includes executable Core/contracts, coordinator, Native/Docker adapters, standalone migration support, protected recovery/coordinator self-update, CLI/MCP and a dedicated Updater Web UI. No Studio integration is required.

| Area | Evidence | Release/live state |
| --- | --- | --- |
| Core/schema/dependency planning | `src/flamoris_update_core`, direct/shared-resource and adversarial graph tests | Live owner/resource inventory pending |
| Exact signatures/catalog/notes | Adapter models/signing/sources/releases, replay/rotation/large-notes tests | Keys/origins/catalogs unprovisioned |
| Durable Jobs/auth/journals | Coordinator/authority/SQLite, effect crash/revocation/duplicate tests | Real filesystem/capacity certification pending |
| Native/Docker/helper/host API | Verified indexes/OCI layers, bounded commands and peer-checked socket | Real units/daemon/TLS/owner acceptance pending |
| Standalone migration runner | Actual isolated SQLite migration/crash tests | Application-specific baseline handlers remain A1 |
| Linked recovery and coordinator self-update | Snapshot/transfer/finalization/epoch/probe/self-failure regressions | Stable independent installation and live rehearsal pending |
| MCP/CLI | Actual SDK, fourteen typed tools and five entry points | Client/operator provisioning pending |
| Dedicated Updater Web | Included assets and same-coordinator session/CSRF API tests | Deployment browser/accessibility acceptance pending |
| Packaging/CI | Wheel/sdist, schema export; amd64/arm64 indexed bundles and CLI startup verification | No published release |
| Release signing pipeline | Manual isolated Environment workflow produces a reviewable signed candidate | Not run; no production tag/key/Environment/publication |

## Verification

Final automated suite: **102 tests** (strict parsing/planning, real isolated migration transactions, crash/replay, authorization, Web/MCP, artifacts and protected recovery). Lint/format, package build, exported schemas, local documentation links and Native bundle staging/CLI startup are checked. GitHub CI verifies both architectures; the final PR records its exact commit and check conclusions.

[Implementation review](docs/IMPLEMENTATION_REVIEW.md) records two review/fix rounds, corrected counterexamples and test limits. Earlier [draft review](docs/REVIEW_DRAFT_1.md) and [design loop](docs/REVIEW_LOOP_2026-10-08.md) remain historical documentation evidence. They preceded the later implementation authorization.

## Entry policy and remaining adoption

AI-side baseline v0.1 → managed v1.0; GPU Node Manager v1.1 → managed v1.2; Updater begins at v1.0. These targets do not certify actual deployed versions. Release and config/database/data schema versions are independent.

A1 application-specific transitions/maintenance owners, A2 release-owner trust/publication and D1 private inventory/profile provisioning/real rollout remain separate. Root helper/executor and recovery-controller self replacement require bootstrap maintenance; only the coordinator has the protected automated self route. No real host, application data, other repository, production keys or published release was changed by this implementation task.

Read [running](docs/RUNNING.md), [roadmap](docs/ROADMAP.md), [adoption](docs/ADOPTION.md) and [acceptance](docs/ACCEPTANCE.md) before deployment. Source/CI completion is not live acceptance.

## Application adoption work — 2026-10-08

The subsequent user request authorizes implementation/review of seven application
repositories and an independent entry updater. Read [application entry](docs/APPLICATION_ENTRY.md).
Source now includes an MCP-independent SDK distribution, durable application
admission, separate mTLS Owner endpoint, bounded tree snapshots/isolated copies,
PostgreSQL dump/isolated restore and a standalone plan/apply/status CLI. The seven
application-specific owner hooks remain in their owning repositories.

Local checkpoint: 122 tests passed; 2 real PostgreSQL integration tests skipped
because this work environment cannot run the required non-root PostgreSQL/user
namespace setup. Those tests have a dedicated real isolated-restore CI job.
This is an implementation checkpoint, not completed review/CI or restore evidence.
Read-only live observations were used during adoption research; no live changes
were made. Signed releases, private trust/profile provisioning, enrollment and
host rollout remain unperformed. Adoption PRs and final review/CI are pending.
