# Progress

Updated: 2026-10-08.

## Current state

**Latest application adoption checkpoint:** independent entry-updater source and
seven application Owner integrations passed the review/fix loop and CI. See
[adoption review](docs/ADOPTION_REVIEW.md) for exact evidence. Application source
PRs were merged after explicit user approval; release publication and live adoption
are pending. The integration record below identifies all eight merged PRs.
The implementation-only sections below preserve the earlier v1 checkpoint.

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


### Adoption review checkpoint

Updater PR #6 tracks the standalone application-entry implementation. CI run
37764725423 at fadd7358e630af6cb932904e62fe50e3cae9f45a passed the real PostgreSQL 14
isolated restore, ordinary verification/SDK build, and amd64/arm64 bundles.
The restore comparison correction scopes source and cloned role memberships
identically and canonicalizes timestamp/interval/float serialization.

Further local review corrected protected environment/configuration checks between
entry effects, application Job configuration binding, snapshot directory/metadata
durability, and Docker activation attestation of mounts/ports/security/limits.
Local suite: **132 passed, 2 real PostgreSQL tests skipped**; those skipped tests
are exercised by CI. These corrections require final CI at their own revision.
Seven application owner/retained-state tests are added in their owning repos;
matched SDK/dependency pins and application CI are being prepared.
No publication, trust provisioning, live writes or enrollment has occurred.


### Historical source handoff and dependency-access blocker

SDK revision d9f010a92ff6e8a1e7a3b7fad8817850bdfb72cd passed final Updater
CI run 37765729268 (verify, real isolated restore, amd64 and arm64 bundles).
All seven applications passed their local complete Python suites and built
wheels from sdists; declared Owner entrypoints/modules are packaged.
Adoption PRs: Agent #45, Studio #69, Intelligence #14, Generation MCP #74,
Controller #9, Hub #41 and GPU Node Manager #13.

Their CI attempts fail at SDK dependency retrieval: Updater is private and
anonymous archive downloads return 404. Studio web CI succeeded independently.
No repository visibility or credential setting was changed. Final application
CI/review remains blocked pending authenticated dependency access or an explicit
publication decision. Read [adoption review](docs/ADOPTION_REVIEW.md) for exact
counts, runs, corrected findings and source/operational limits. All PRs remain
draft; releases, profiles/trust, enrollment and live rollout are unperformed.

### Public SDK and final source review

The operator made Updater public, resolving the SDK archive 404. All seven
application CI runs now succeed, including Agent/Studio disposable PostgreSQL,
installed package checks and actual application containers. Agent container CI
exposed duplicate cryptography wheels; the source-only Intelligence wheel build
now uses --no-deps and the final image runs pip check. Corrected Agent revision
d7b7b26318c246c7a202f966438775d63fe6410c passed both jobs in run 37768251469.
The SDK source pin remains d9f010a92ff6e8a1e7a3b7fad8817850bdfb72cd.

Source review/fix and automated integration verification are complete. Eight PRs
are prepared for human review. GPU's agreed entry remains 1.2.0; the six AI-side
applications target 1.0.0. Private profiles, retained unsupported-resource
handling, signing/trust, release publication, enrollment and real-host rollout
remain operational work. The entry CLI accepts already current schemas; unknown
outcomes retain claims and require reconciliation instead of replay or automatic
data rollback. No live writes, enrollment or application merges occurred.

### Main integration after explicit merge authorization

All eight PRs were merged by squash after successful CI at their reviewed heads
and an explicit user instruction on 2026-10-08. Earlier review-ready checkpoints
above are historical. Their fixed SDK/library source revisions remain unchanged
and readable after merge; no branch cleanup, new release tag or live change was
performed.

| Repository | Merged PR | Main integration commit | Successful reviewed-head CI |
| --- | --- | --- | --- |
| flamoris-updater | [#6](https://github.com/flamoris-jp/flamoris-updater/pull/6) | `5af6d6acee827817515b16a13384f6a3d433d672` | 37769070260 |
| flamoris-generation-controller | [#9](https://github.com/flamoris-jp/flamoris-generation-controller/pull/9) | `5ab80f60d1de6fcf53ffedc0c0dec1cd8cd3da60` | 37769076548 |
| flamoris-intelligence-mcp | [#14](https://github.com/flamoris-jp/flamoris-intelligence-mcp/pull/14) | `d6d23e028e88ead8efb6b8349f2819d612619d0c` | 37769104360 |
| flamoris-ai-agent | [#45](https://github.com/flamoris-jp/flamoris-ai-agent/pull/45) | `e6988272c79ba8454f7bf4761dad209577cd3ac4` | 37769085303 |
| flamoris-generation-mcp | [#74](https://github.com/flamoris-jp/flamoris-generation-mcp/pull/74) | `484029e52a21895b9f33a3c69053b5109dfd9c7d` | 37769091122 |
| flamoris-studio | [#69](https://github.com/flamoris-jp/flamoris-studio/pull/69) | `5729cc927d5c4311c4b9a45c5aa450cc80c4eb0f` | 37769318514 |
| flamoris-mcp-hub | [#41](https://github.com/flamoris-jp/flamoris-mcp-hub/pull/41) | `43c604cd14e129a09ee4e63fd04433c92867753e` | 37769324654 |
| flamoris-gpu-node-manager | [#13](https://github.com/flamoris-jp/flamoris-gpu-node-manager/pull/13) | `b6871b67ef9086dabc624da4c08632c49200bb72` | 37769331234 |

Before real-host entry, prepare signed immutable candidates, protected deployment
profiles and trust, independent Owners/helper/entry CLI and verified backup/restore.
Stop legacy services and all external writers under the approved maintenance
procedure, run the reviewed source/plan/apply transition, validate the entry
versions, then enroll their verified transition evidence in the ordinary Updater
coordinator. The six AI-side packages enter at 1.0.0 and GPU Node Manager at 1.2.0.
Controller travels inside its one hosting Generation artifact. This merge does
not assert current live versions/schemas or authorize a real-host change.

### Pre-deployment retained-resource correction

The first private inventory review found normal setgid shared directories and
application-owned retained trees that the merged entry contract did not yet
represent. Source work now accepts setgid on directories only and preserves it
through snapshot/restore verification; setuid, sticky directories, setgid files,
links, hardlinks and special files remain refused. Controller and Studio updates
expand their explicit Owner resource sets for provider inputs/definitions/recipes/
state and thumbnails respectively. Linux verification at this checkpoint is
**137 passed, 2 skipped** for Updater, including Ruff, format and documentation
link checks. Matched dependency pins, PR review and CI at the new revisions are
pending. No service, production data, trust, release, enrollment or host
configuration was changed by this checkpoint.

### Pre-deployment Docker restart correction

The live binding review found that replacement containers would otherwise lose
their approved restart policy. Docker bindings now require an explicit
`always` or `unless-stopped` policy; activation applies it
and post-start attestation rejects drift. Linux verification is **139 passed, 2
skipped**, with Ruff, format and documentation-link checks successful. PR review
and CI at the new revision remain pending. No live service or host was changed.
