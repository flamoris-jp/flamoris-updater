# Progress

Updated: 2026-10-10 (JST).

## v1.0.0 distribution preparation

The user authorized Updater v1.0 and distribution creation. Package version remains
1.0.0, with release tag v1.0.0. The merged main source is verified in CI run
38018447434. Release preparation updates stale notes/security wording to the
current simple-bootstrap, self-update and diagnostic contracts and adds the
version-scoped publication workflow. No product behavior or app feature is added.

The workflow builds/exercises indexed native bundles on amd64/arm64, includes
Updater/Core wheel/source and schemas, statically verifies both archives again,
and creates exact source metadata, installation instructions and SHA-256 sums.
Only its trusted main publication job receives contents-write authority; a
failed upload is not permission to replace a published release asset. The existing
protected advanced signing workflow remains separate. Initial distribution uses
GitHub HTTPS and checksums, not a synthetic signing identity or signed catalog.

Local verification: **234 passed, 7 skipped**; Ruff lint/format, documentation
links, workflow YAML and shell syntax, and whitespace checks pass. Distribution
tests reject digest/version/platform mismatches, missing or unexpected assets,
and replacement of an already assembled output. Publication is still pending
at this source checkpoint; GitHub CI/release metadata provide its final evidence.

This release contains Updater only. Application artifacts and their direct HTTPS
catalog, external infrastructure provisioning and real-host installation remain
separate work. Latest build/publication evidence is recorded in the release/PR.

## PR #11 merged; PR #14 reconciled with main

PR #11 was squash-merged into main at
`c21ef02794ab8c3917a20539e4cf253e1d936136`. Its complete Git tree is identical
to the reviewed PR #11 head `1b12c503630eff29fa394674967578d709c1ce3f`
(`6d4e1247456d77cc5fb94d08f287e5531a07b06f`). The subsequent PR #14 conflict
was caused by changed ancestry, not different installation source contents.

PR #14 now targets main and incorporates that main commit with a merge commit,
preserving the already validated self-update, continuing MCP credentials and
diagnostic/layout source. No application code, configuration or test behavior is
changed by this reconciliation. Documentation links are checked locally; latest
CI and mergeability evidence are recorded in PR #14. PR #14 remains reviewable;
no release publication or real-host changes are performed.

## AI-readable diagnostics — implemented and locally verified

The user's additional authorization covers structured evidence for AI recovery
procedure preparation and installation documentation, plus an explicit manual
recovery guide when Updater is stopped. PR #14 now includes ordinary app and
self-update timelines, bounded exit/errno/SQLSTATE/fixed-hint failure records and
read-only application-scoped MCP log/layout tools. No automatic recovery, external
installation, new DB migration, release publication or real-host change is added.

Intent is durably committed and privately exported before effects. Current,
candidate and previous layout distinguish recorded bindings from live state;
Server Manager remains the current infrastructure observation authority. Offline
JSONL/layout mirrors support manual inspection during Updater downtime. Existing
records tables are reused without a DB schema upgrade. See
[diagnostics and manual recovery](docs/DIAGNOSTICS.md).

Local suite: **227 passed, 7 skipped**. Ruff/format, JavaScript syntax, doc links,
strict schema export, Updater wheel/sdist and the actual amd64 indexed bundle
with all installed entrypoints pass. Tests cover durable pagination/export,
secret exclusion, bounded diagnostic classification, logging-write/quota failure
before effects, install/setup/update interruption and app-scoped read-only MCP.
Self-update still passes both actual read-only SQLite probes. The latest GitHub
CI result is recorded in [PR #14](https://github.com/flamoris-jp/flamoris-updater/pull/14).
The earlier logging investigation below is historical and superseded by this
authorized implementation; its missing features are no longer the source status.

## Previous checkpoint: self-update and MCP continuity — source verified

Implemented on the direct-install source (PR #11) in
[PR #14](https://github.com/flamoris-jp/flamoris-updater/pull/14), targeting that
feature branch so the two authorized additions can be reviewed independently.
Authorized scope is Web/root-manager self-update and persistent MCP credentials,
plus investigation of existing logs. No external software installation, failure
recovery, DB/journal migration, ordinary app log feature, release or live change.

- New bootstrap installs an independently pinned root supervisor alongside Web
  and manager. Indexed compatible self releases are immutable catalog bindings.
  It stages/verifies code, stops those two services, runs actual candidate probes
  of both existing journals read-only, checks bootstrap config/unit bindings,
  switches/starts, and verifies both live versions/runtime paths. Existing config,
  credentials and history remain in place. The original supervisor installation
  stays pinned; staged self bundles are retained, not automatically cleaned.
- Web can issue/read metadata/rotate/revoke read-only or read/execute integration
  keys. Secrets appear once and are hashed at rest; service principals cannot
  issue credentials or grants. Owner changes/disablement invalidate keys. Existing
  24-hour tokens remain. Stateless MCP reconnects with the same valid key after
  update downtime; client retry and proxy/tunnel management remain external.
- Self Jobs record step intents/outcomes/times for MCP Job/history inspection.
  Unknown/interrupted work stops without replay or rollback and blocks local
  operations. The ordinary manager does not execute/reconcile supervisor Jobs.
- Logging investigation finds ordinary MCP exposes latest phase/step/error and
  retained state, but no complete app step timeline, command diagnostics or MCP
  event-log reader. This is insufficient for reliable cause diagnosis through
  Updater MCP alone; enhancements require separate user approval.

Local suite: **216 passed, 7 skipped**. Ruff/format, JavaScript syntax, docs links,
schema export, Updater/Core wheel/sdist builds and actual amd64 indexed bundle
runtime identity/entrypoints pass. [CI run 38010234118](https://github.com/flamoris-jp/flamoris-updater/actions/runs/38010234118)
on implementation commit `d7f5f427a287b29a36aa19f527e795c1d3c8e921` passed all
five jobs: ordinary verification/build/docs/schemas, root managed/self flows with
real PostgreSQL initialization, actual Generation Docker install/start/health,
and amd64/arm64 indexed bundle/runtime identity checks.
Self Job tests use actual indexed staging and
read-only SQLite probes with controlled systemd/runtime identity commands.
Web/MCP tests cover expiry/restart, scope, secret redaction, rotation/revocation
and owner invalidation. Bundle CI adds actual packaged runtime identity checks
on amd64/arm64. These do not certify real service replacement or external clients.
Read [self-update and logging review](docs/SELF_UPDATE.md).

## Simple installation and update — source and CI verified

Current authorization covers the agreed source changes, tests/CI and a reviewable
PR; no live host changes or release publication. PRs #12 and #13 are merged.
[PR #11](https://github.com/flamoris-jp/flamoris-updater/pull/11) carries forward
its direct-install source (`a049b990f872996e5c0c1a38891caac858cf57df`) on current
main, without unmanaged import, client PKI or backup prerequisites.

Implemented:

- Removed DB/system backup and data-restore contracts and implementations.
  App-owned migration/fencing remain in the advanced Core route.
- Empty-host bootstrap installs two services, with unprivileged Web and a local
  OS-peer-checked root manager. Web first setup consumes a one-time code and
  configures the administrator and an ordinary HTTPS release catalog.
- Per-app install allows later independent additions. Required providers and
  installed consumers constrain only their real compatibility dependencies.
- Web, MCP and CLI share eight managed operations, persistent jobs and history.
  Install provisions stopped applications and waits for their first setup;
  explicit start and verification finish installation.
- Schema/settings-compatible updates stage new executables beside the current
  version, retain installed settings, switch and verify. After success, keep one
  previous executable and prune older recorded executables/package caches.
  Failures/unknown outcomes block cleanup and replay. Web allows manual deletion
  of the previous executable. Config/data/DB/shared infrastructure/external AI
  runtimes and models are never cleanup targets.
- Candidate/catalog recipe builders cover six deployment units. Updater package,
  Native bundle launchers, schemas and run/setup documentation include this path.

Local verification: **198 passed, 7 skipped**. The skips are actual PostgreSQL/
Docker integrations and named Unix listeners unavailable in this environment;
CI has dedicated real PostgreSQL and Generation Docker tests. Real offline
Native wheel/venv staging, settings/data retention, socket-pair OS credentials,
Web/MCP/CLI shared jobs, failures and path boundaries pass locally. Ruff/format,
JavaScript syntax, documentation links, schema export and Updater/Core wheel/
sdist builds pass. These results do not certify all app domains or real hosts.

[CI run 37967458776](https://github.com/flamoris-jp/flamoris-updater/actions/runs/37967458776)
on source commit `4e10f7837cba9118f063a060ed443d84c61e52fc` passed all five
jobs: ordinary verification/build/schemas/docs, actual stopped Generation Docker
provision/start/health, new PostgreSQL DB/role initialization plus managed flows,
and amd64/arm64 indexed Native bundle verification. Its first predecessor run
exposed the known OS-peer rejection/reset race; that was corrected and verified,
not suppressed. The final documentation-only commit is also checked on PR #11.

Limits: release candidates/catalogs are not published; six actual application
first setups and external connections have not been accepted on real hosts.
The simple route requires explicit schema/settings compatibility; new app schema
handlers and older SDK pin integration remain separate app-owned work. Root
helper/Updater self replacement remains reviewed maintenance. Direct HTTPS
artifact locations are required; automatic tunnel management is not included.
See [review evidence](docs/SIMPLE_REVIEW.md) and [running](docs/RUNNING.md).

The sections below are historical checkpoints; their old backup/import/self
integration status does not describe the current simple installation path.

## Removal of private CA and client certificates

Implemented from current main (PR #12 merged), independently of open PR #11.
Removed client CA/certificate/key configuration from API clients, release and OCI
fetching, the CLI and the host API. Owner services now use protected local Unix
sockets and Linux OS peer identity; callers verify the Owner UID before sending.
Host APIs bind loopback only for direct/tunneled connections and retain the
helper's signed request/operation authorization. Public coordinator HTTPS,
Web/session/CSRF, Bearer tokens and release/operation signatures remain.

This changes Owner SDK/configuration compatibility. The seven application SDK
pins/artifacts are not repinned here; current older artifacts need coordinated
integration. The existing backup/recovery protocol and the initial-install/update
connection are separate work. There is no automatic Updater bootstrap or tunnel
manager; [transport](docs/TRANSPORT.md) documents actual installation steps/limits.

Local verification: 162 tests passed; 2 PostgreSQL and 5 named-socket listener tests skipped due to environment limitations. Real socket-pair OS peer/operation/quota tests passed; GitHub CI runs the listener and PostgreSQL integrations. Ruff/format, documentation links, exported configuration schemas and both Updater/Core wheel/sdist builds passed. Built Core/Updater artifacts include the new local transport and no Owner client-PKI code. The first CI pass exposed omitted required null fields in initial Owner inspection; its serialization and a regression test are corrected. Loopback CLI calls preserve the configured public Host through `--public-origin`. [PR #13](https://github.com/flamoris-jp/flamoris-updater/pull/13) tracks exact-head CI. No real-host change, release publication or merge.

## Removal of unmanaged-deployment import

Implemented on a dedicated branch from current main, separately from PR #11.
Removed the `flamoris-updater-entry` command/module/bundle launcher, registration
MCP/Web/CLI tools, the `enroll` plan action and authority role, transition evidence
and the legacy-state inspection helpers used only by that command. Normal
managed updates, installation contracts, application-owned schema migration and
recovery remain. API/schema compatibility is intentionally changed: old import
plans and evidence are not executable or automatically converted.

Local verification: 146 tests passed, 2 PostgreSQL integration tests skipped
(the existing dedicated CI job runs those integrations). Ruff/format, JavaScript
syntax, documentation links and exported schema checks passed. Updater and Core
wheel/sdist builds passed; the Updater artifacts contain five console commands
and no entry module, and the exported MCP catalog contains twelve tools.

The dedicated removal [PR #12](https://github.com/flamoris-jp/flamoris-updater/pull/12)
tracks CI at its exact head. No merge, release publication, real-host change,
deletion of live applications or live install has occurred. The new simple installation/first-setup/update flow remains separate
work; source deletion is not evidence that this flow is complete.

## Historical checkpoints

The records below describe prior source and CI work. Their import/entry rollout
instructions are superseded and must not be used as the current procedure.

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
and post-start attestation rejects drift. Linux verification is **140 passed, 2
skipped**, with Ruff, format and documentation-link checks successful. PR review
and CI at the new revision remain pending. No live service or host was changed.
