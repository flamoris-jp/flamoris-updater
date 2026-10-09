# Adoption inventory and implementation boundaries

> For current fresh-install behavior, use [INSTALL.md](INSTALL.md). The legacy
> baseline-entry command is removed; the older transition gates below are
> historical and do not require installing an old version before a fresh target.

> Subsequent application adoption source is tracked in PR #6 and
> [ADOPTION_REVIEW.md](ADOPTION_REVIEW.md). Earlier A1 status below is historical;
> application source review/CI is complete, and live rollout remains pending.

**Source inspection: 2026-10-08. No live infrastructure inspection or change.**

This is a design input, not an assertion that repositories contain Updater-compatible releases. Live artifact identities, DB schemas, private deployment mappings and signing keys remain unverified. Use Server Manager when live state is required.

## Inspected source

| Repository | Pinned source checked | Design implication |
| --- | --- | --- |
| [Studio](https://github.com/flamoris-jp/flamoris-studio/blob/d03028df892f7b1dc658534d22abaffcc34a5134/pyproject.toml) | d03028d | Python >=3.12; owns its application DB/Alembic and creative user sessions; an update target, not the Updater UI owner |
| [Agent](https://github.com/flamoris-jp/flamoris-ai-agent/blob/d5dd2e0a922e08e3054a71defb7f79b40d754a28/pyproject.toml) | d5dd2e0 | Python >=3.11; own SQL migration history and conversation data |
| [Controller](https://github.com/flamoris-jp/flamoris-generation-controller/blob/2e85caac885a84a851d92a7864e7b94c4f95ad86/docs/MIGRATION.md) | 2e85caa | Importable shared authority hosted with Generation; recipes/assets/unknown reservations must be preserved |
| [Hub](https://github.com/flamoris-jp/flamoris-mcp-hub/blob/e74f2cfa45e5ea57ec0996c6d7a6e83c5c4b4aee/pyproject.toml) | e74f2cf | Python >=3.11; external routing/catalog, not application schema owner |
| [GPU Node Manager](https://github.com/flamoris-jp/flamoris-gpu-node-manager/blob/2f55fb74b986b7fa9c0eceb00cab2bd94187fdca/docs/ARCHITECTURE.md) | 2f55fb7 | Existing manager/lock owns lifecycle; current source package version 1.0.0 differs from the agreed baseline release label |
| [AI Runtime](https://github.com/flamoris-jp/flamoris-ai-runtime/tree/e2f4ff709246922674d99344e02c8ce364f9e8f2) | e2f4ff7 | Native C++ project; managed deployment is not inferred from source presence |
| [MCP Core](https://github.com/flamoris-jp/flamoris-mcp-core/blob/a21e82519e94d923503cb64f3c10e6289f22e995/README.md) | a21e825 | .NET library; reuse principles rather than importing it into Python |
| [Logging](https://github.com/flamoris-jp/flamoris-logging/blob/c2ef62c257c5b9a1bb76a8960f1c805630c1f320/README.md) | c2ef62c | .NET library; no direct Python package reuse |
| [AI coordination](https://github.com/flamoris-jp/flamoris-ai/blob/ab16166d0711b0c7567c188aabedfe36dd4d27bc/PROGRESS.md) | ab16166 | Source/live evidence is explicitly separated; operational release history is not a current health probe |

Agent/Studio and Controller package dependencies demonstrate why releases must describe embedded components independently of deployment units. This inspection does not infer the complete list of installed applications.

The agreed GPU Node Manager baseline remains v1.1 and management entry remains v1.2. The checked core source package reports 1.0.0; a release tag, deployed core package and host-specific wrapper can have different versions. Resolve their mapping during enrollment rather than changing the user's entry policy or declaring the baseline wrong.

## Application work required before enrollment

| Owner | Required contract/adoption work |
| --- | --- |
| Studio | Preserve user/session/history data and Alembic lineage; maintenance admission gate; runtime/migration roles; no Updater UI integration |
| Agent | Preserve SQL history, principal/session/personality/continuation data; drain inference; fence retention/admin writers; scoped backup/restore |
| Generation + Controller | One deployment owner; preserve recipes, ComfyWorkFlow definitions, inputs/assets, copies and unknown reservations; explicit maintenance fence |
| Intelligence service | Signed deployable release and embedded-provider inventory; drain inference/unknown work; provider-safe health profile |
| Hub | Stable external catalog revision/compatibility; gate routed writes during affected groups; signed config migration |
| GPU Node Manager | Standalone v1.1 → v1.2 transition; preserve common locks and runtime evidence; maintenance coordination through the manager |
| Host-specific wrappers | Declare exact embedded core and binding identities in restricted deployment profiles; preserve package/release separation |
| AI Runtime, Observer and other services | Candidate later targets only after actual installation, scope and entry policy are verified |

Current Controller API exposes health/reservation evidence, not a documented Updater-exclusive maintenance fence. Manager's existing lock does not by itself prove a cross-host update-maintenance contract. These gaps must be implemented in the owning applications before automatic updates; Updater must not fabricate drain endpoints or treat an idle snapshot as exclusivity.

No owning repository is modified by this design. The seven-baseline-tag context is not used to guess seven independently restartable services.

## Required private deployment inventory

For each deployment record actual host/deployment/application IDs, release/artifact/component mapping, mode/platform, approved release sources, lifecycle bindings, config/secret references, persistent resource/schema ownership, all writers/timers, DB roles, backup/restore domains, entry-transition evidence and validation contracts.

For each shared resource record the consistency group, external effects and all participants required to fence/restore. For each provider record supported drain/reconcile behavior; an unreachable or unknown job is a blocker.

A portable public example uses fictitious IDs only. Do not publish private topology, actual hostpaths, secrets or operational receipts here.

## Work packages and implementation boundary

These are scoped backlog proposals, not created Issues or implementation authorization.

| Work package | Owner | Depends on | Completion evidence |
| --- | --- | --- | --- |
| U1 Manifest/trust/catalog parser | Updater Core/adapters | Draft review | Strict validation, signatures, digest/platform selection and replay/revocation failures |
| U2 Planner/schema graph/groups | Updater Core | U1 + verified resource contracts | Exact provider bindings, incoming consumers, deterministic schema route, blocked ambiguity and mixed-version scenarios |
| U3 Journal/authorization/jobs | Updater Core/adapters | U2 | One consumed plan, immutable operations, durable maintenance/finalization and linked-recovery ownership evidence |
| U4 Native host executor and Docker/Native profiles | Updater adapters | U3 + application maintenance contracts | Typed local privileges, no caller-selected commands/mounts, staging/activation tests |
| U5 Backup/recovery/self-update controller | Updater + backup/app owners | U3/U4 | Side-effect-isolated restore, group failure, epoch handoff and all-control-state-preserving self rollback |
| U6 MCP/operator interfaces | Updater adapters | U3/U5 | Catalog/schema/scope parity, authorized Job start and safe cancellation |
| A1 Standalone entry migrations | Each application | Migration contract + live inventory | Preserved data/roles/history and enrollment receipts; independently executable |
| A2 Release packaging/signing | Each application + release owners | U1 trust profile | CI-built immutable release, components, notes and matching signed Manifest |
| D1 Initial Updater install/enrollment | Deployment owners | A1/A2 + U1–U6 | Verified current entry versions; private receipts and recovery bundle |
| U7 Dedicated Updater Web | Updater adapters | Stable coordinator/operator contract | Independent auth/session/CSRF, safe summaries and same Job authority; no Studio dependency |

No live acceptance, trusted signing keys or release-ready status is implied by this backlog.

## Review-derived adoption gates

Private profiles must resolve dependency providers/incoming consumers, physical resource aliases, one resource owner and all restart/timer paths enforcing durable maintenance epochs. Application startup must support controlled maintenance validation rather than automatically migrating or replaying jobs.

Recovery-controller bootstrap provisions the normal coordinator epoch, outage-independent recovery CLI and supported executor handoff. Entry evidence is typed (transition, installation or supported adoption), and each is re-inspected before inventory commit. Missing contracts keep automatic updates blocked; this review adds no application implementation or live validation.

## Source implementation checkpoint

Updater-owned U1–U7 source is implemented and tested; see [roadmap](ROADMAP.md) and [implementation review](IMPLEMENTATION_REVIEW.md). The table above preserves package ownership and adoption gates. A1 application-specific contracts/entry handlers, A2 production keys/catalogs/publication and D1 real inventory/profile provisioning/rollout remain pending. No live system, other repository or production credential was modified by this implementation.
