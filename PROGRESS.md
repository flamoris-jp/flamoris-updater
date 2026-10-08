# Progress

Updated: 2026-10-08.

## Current state

**Basic design + detailed design draft 1. Implementation explicitly held.** No executable Updater, Manifest validator, migration runner, published release, MCP server, CI/deployment setup or live acceptance exists.

| Area | State | Evidence / next step |
| --- | --- | --- |
| Project identity and accepted boundaries | Documented | [README](README.md), [basic design](docs/DESIGN.md) |
| Platform/packages/Core ports | Draft 1 documented | [Detailed design](docs/DETAILED_DESIGN.md) |
| Manifest, artifact/signature/catalog and notes | Draft 1 documented | [Manifest](docs/RELEASE_MANIFEST.md) |
| Schema graph, runner and standalone entry | Draft 1 documented | [Migration](docs/MIGRATION_CONTRACT.md) |
| Plans/authorization, Job/journal and group/self recovery | Draft 1 documented | [Execution/recovery](docs/EXECUTION_RECOVERY.md) |
| MCP/operator API | Draft 1 documented | [MCP](docs/MCP_API.md) |
| Dedicated Updater Web design | Documented; not implemented | [Web](docs/WEB_UI.md); independent of Studio |
| Source inventory/adoption work | Pinned source inspection documented | [Adoption](docs/ADOPTION.md); live inventory pending |
| Failure and acceptance scenarios | Documented for future work | [Acceptance](docs/ACCEPTANCE.md); not executed tests |
| Contributor/security guidance | Updated for design-only state | [AGENTS](AGENTS.md), [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md) |
| Application-specific maintenance/entry migrations | Not implemented by this task | Owning repositories and actual deployment evidence required |
| Core/wrapper/executors/recovery/MCP | Not implemented | Explicit implementation hold |
| CI-built signed artifacts and trust provisioning | Not implemented | Release-owner work |
| Live enrollment/update/restore | Not performed | No live changes or infrastructure inspection |
| Dedicated Updater Web implementation | Not implemented | Later Updater-owned phase; no Studio integration |

## Fixed management-entry policy

- Installed AI-side applications: agreed baseline v0.1; Updater entry v1.0.
- GPU Node Manager: agreed baseline v1.1; Updater entry v1.2.
- Updater: first managed release v1.0.
- Pre-entry migrations are independently executable application responsibilities.

Release labels, package/component versions and actual deployed identities are distinct. Source inspection does not overwrite these agreed entry targets or certify current live versions.

## Verification

Bootstrap: current template/shared policy reviewed; license and generic Issue forms preserved; local links and portable status checked.

Detailed design: pinned repository/package/ownership evidence inspected, contracts reviewed for crash/replay, schema-vector consistency, authorization, resource/writer fencing, group restoration and self-update continuity. Documentation/examples/links checked. See [review record](docs/REVIEW_DRAFT_1.md).

No runtime tests, CI, release signing, provider calls, DB migrations or deployment acceptance are claimed.

## Web ownership correction (2026-10-08)

The user selected a dedicated Updater Web UI instead of embedding update management in flamoris-studio. Updated architecture/API/adoption/roadmap guidance: Web, CLI and MCP share one coordinator; Web owns its own authentication/session/CSRF. Studio remains only an application update target. Self-update/recovery-controller restrictions and the implementation hold are unchanged.

## Next checkpoint

Implementation remains held at the user's instruction. The next design/adoption input is verified private deployment/resource/writer inventory and application maintenance contracts, followed by a separately authorized implementation task. Proposed work packages in [adoption](docs/ADOPTION.md) have not been turned into Issues or code.
