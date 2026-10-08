# Roadmap

Basic direction and detailed draft 1 are documented. No runtime phase is complete. The current instruction explicitly holds implementation.

| Phase | Work | Acceptance gate |
| --- | --- | --- |
| 0 | Repository identity, accepted direction, contributor guidance | Reviewable documentation with no runtime/readiness claims |
| 1 | Audit installed AI-side applications, persistence, configuration and dependencies | Pinned source inventory documented; exact live migration inventory/private evidence pending |
| 2 | Core, Manifest, migration, enrollment, authorization and recovery contracts | Draft 1 documented; implementation verification and owning-app contracts pending |
| 3 | Application-owned standalone transitions | AI-side v0.1 → v1.0 and GPU Node Manager v1.1 → v1.2 validated independently |
| 4 | Updater v1.0 Core/wrapper, Docker/Native execution and MCP | Deterministic planning, trusted artifacts, durable jobs and recovery evidence |
| 5 | Live enrollment and update acceptance | Entry versions verified, restore and failure scenarios accepted |
| 6 | Dedicated Updater Web management | Independent auth/session, version/candidate, release-note, plan and result UI over the same coordinator |

Application transitions and Updater implementation are separate deliverables. Phase 3 can use the agreed contract without requiring a running Updater. Updater must not take responsibility for the legacy transition.

## Current design deliverable

[Detailed design](DETAILED_DESIGN.md) and linked specifications describe the v1 interfaces, trust, migration, state machine, recovery and [acceptance scenarios](ACCEPTANCE.md). [Adoption](ADOPTION.md) records pinned source boundaries and proposed work packages.

## Implementation hold and future work

Do not start runtime implementation, create runnable schemas/CI/deployment files, apply migrations or change hosts under this design-only instruction.

A later implementation task can:
1. Complete live deployment/resource/writer inventory through the appropriate owners.
2. Freeze application maintenance, backup and pre-entry contracts against that inventory.
3. Split the proposed work packages into owning-repository Issues.
4. Implement and validate the agreed scope, keeping source/release/live evidence separate.

No cross-repository files or live resources are changed by this design deliverable. The Web UI is owned by Updater; no Studio integration work is planned. See [Web design](WEB_UI.md).

## Completion evidence

Track documentation, implemented source, CI/tests, released artifacts and live acceptance separately in [PROGRESS.md](../PROGRESS.md). A merged PR is not proof of a deployed or accepted application.
