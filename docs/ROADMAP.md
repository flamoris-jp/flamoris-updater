# Roadmap

The repository is currently a documentation bootstrap. No runtime phase is complete.

| Phase | Work | Acceptance gate |
| --- | --- | --- |
| 0 | Repository identity, accepted direction, contributor guidance | Reviewable documentation with no runtime/readiness claims |
| 1 | Audit installed AI-side applications, persistence, configuration and dependencies | Exact migration inventory and private deployment evidence |
| 2 | Core, Manifest, migration, enrollment, authorization and recovery contracts | Versioned reviewed contracts and explicit failure semantics |
| 3 | Application-owned standalone transitions | AI-side v0.1 → v1.0 and GPU Node Manager v1.1 → v1.2 validated independently |
| 4 | Updater v1.0 Core/wrapper, Docker/Native execution and MCP | Deterministic planning, trusted artifacts, durable jobs and recovery evidence |
| 5 | Live enrollment and update acceptance | Entry versions verified, restore and failure scenarios accepted |
| 6 | Studio update management | Version/candidate, release-note, plan and result UI backed by accepted contracts |

Application transitions and Updater implementation are separate deliverables. Phase 3 can use the agreed contract without requiring a running Updater. Updater must not take responsibility for the legacy transition.

## Next work

1. Audit the current repository versions and actual deployment boundaries; use Server Manager for current infrastructure state.
2. Identify exact applications to onboard and application-owned migration gaps.
3. Resolve the detailed decisions in [design](DESIGN.md) and specify [contracts](CONTRACTS.md).
4. Create implementation Issues with scope, dependencies, acceptance evidence and owning repository.

This setup does not create cross-repository implementation changes or perform live migration. Those require their own concrete work items.

## Completion evidence

Track documentation, implemented source, CI/tests, released artifacts and live acceptance separately in [PROGRESS.md](../PROGRESS.md). A merged PR is not proof of a deployed or accepted application.
