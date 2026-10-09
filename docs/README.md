# Documentation

Updater-owned v1 source is implemented. Models/exported schemas and [running procedures](RUNNING.md) define executable behavior; [implementation review](IMPLEMENTATION_REVIEW.md) separates automated evidence and remaining integration work. Detailed design examples remain illustrative where marked.

| Document | Purpose |
| --- | --- |
| [Running](RUNNING.md) | Setup, processes, authorization, protected recovery and release procedure |
| [Implementation review](IMPLEMENTATION_REVIEW.md) | Source counterexamples, regression tests and verification limits |
| [Basic design](DESIGN.md) | Accepted ownership, scope and installation targets |
| [Detailed design](DETAILED_DESIGN.md) | v1 choices, package boundaries, identities and Core ports |
| [Contract index](CONTRACTS.md) | Links to the draft contracts |
| [Release Manifest](RELEASE_MANIFEST.md) | Strict JSON, artifacts, signatures/catalog and release notes |
| [Migration contract](MIGRATION_CONTRACT.md) | Schema-vector graph, normal migration runner and fences |
| [Execution/recovery](EXECUTION_RECOVERY.md) | Plans, authorization, journals, multi-host failure and self-update |
| [MCP API](MCP_API.md) | Typed tool catalog, scopes and Jobs/errors |
| [Dedicated Web UI](WEB_UI.md) | Updater-owned operator screen and independent auth/session |
| [Source integration](ADOPTION.md) | Pinned source inspection and owning-repository work |
| [Acceptance](ACCEPTANCE.md) | Automated evidence and live acceptance criteria |
| [Draft 1 review](REVIEW_DRAFT_1.md) | Historical draft findings and verification limits |
| [Review/correction loop](REVIEW_LOOP_2026-10-08.md) | Two rounds, final consistency fixes and future counterexamples |
| [Roadmap](ROADMAP.md) | Source completion and separate integration work |
| [Progress](../PROGRESS.md) | Actual design/source/release/live state |
| [Contributor guide](../CONTRIBUTING.md) | Change and review workflow |
| [Agent guide](../AGENTS.md) | Implementation authorization and ownership rules |

AI-side installation target is v1.0, GPU Node Manager v1.2 and Updater v1.0. Unmanaged deployment import is unsupported; initial installation and its update connection are separate work.
