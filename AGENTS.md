# AGENTS.md

This repository is part of the FLAMORIS ecosystem.

AI agents and human contributors should inspect the current repository before making substantial changes. Do not assume that setup, build, deployment, service names, paths, configuration, or architecture match another FLAMORIS repository.

## Core principles

1. **Current implementation is authoritative**
   - Read the repository documentation, configuration, tests, and relevant source before changing behavior.
   - Do not invent repository-specific commands, paths, services, or configuration.

2. **Keep responsibility clear**
   - Keep this repository focused on its documented purpose.
   - Preserve application and service ownership boundaries.
   - Do not create a second source of truth for state owned elsewhere.

3. **Reuse deliberately**
   - Check existing FLAMORIS shared packages and repositories before duplicating common infrastructure.
   - Reuse code only when the dependency direction and ownership boundary remain clear.
   - Avoid speculative abstractions for requirements that do not yet exist.

4. **Security and privacy are architectural requirements**
   - Never commit or log secrets, credentials, tokens, private keys, or sensitive user data.
   - Prefer least-privilege access and bounded resource use.
   - Treat external input and remote responses as untrusted.

5. **Stable behavior over cleverness**
   - Prefer explicit, testable contracts and straightforward implementations.
   - Preserve existing public behavior unless a change intentionally modifies it.
   - Document externally visible behavior and compatibility impact.

6. **Documentation must track reality**
   - Mark the current implementation/status explicitly when a repository has both shipped behavior and future phases.
   - Do not describe implemented behavior as merely planned, and do not describe planned behavior as already shipped.
   - Keep public architecture portable. Machine names, private topology, credentials, and deployment-only paths belong in private deployment documentation rather than public repository defaults.

7. **AI-native, human-authoritative**
   - AI-assisted development is welcome.
   - Humans remain responsible for reviewing behavior, security, licensing, and compatibility.

## Before implementing a substantial change

- read this file and README.md;
- identify **what this repository is, what it owns, what it does not own, its current status, and where it fits in FLAMORIS**;
- read the [organization map](https://github.com/flamoris-jp/.github) and the relevant family map when cross-repository context matters;
- read relevant docs, Issues, and Pull Requests;
- inspect current implementation and tests;
- identify the source of truth and dependency direction;
- check whether reusable FLAMORIS infrastructure already exists;
- verify repository-specific setup and deployment details instead of guessing.

## Testing

Add or update tests where practical.

Prefer deterministic tests and explicit contracts. When behavior differs by platform, runtime, provider, or environment, document the supported boundary and test the relevant cases.

## Licensing

Unless stated otherwise, code in this repository is licensed under Apache License 2.0.

Do not add third-party code, models, model weights, datasets, fonts, media, or generated assets unless their licenses are compatible and clearly documented.

## Support

FLAMORIS does not provide guaranteed individual support.

Use the repository documentation, Issues, tests, logs, and source code as primary references when diagnosing problems.

## FLAMORIS Updater boundaries

- Python 3.12 v1 source is implemented under the 2026-10-08 instruction. Inspect src/, tests/, pyproject.toml, docs/RUNNING.md and PROGRESS.md; distinguish source/CI evidence from publication and live acceptance not performed.
- Read docs/DESIGN.md, docs/CONTRACTS.md, docs/ROADMAP.md and PROGRESS.md before substantial work.
- Keep reusable Core and the FLAMORIS wrapper in this repository. Core must not depend on FLAMORIS policy, deployment identities, MCP or Studio.
- Operator Web UI belongs to Updater in this repository. Do not embed update management in flamoris-studio or add a dependency on its authentication, database or availability. Web, CLI and MCP adapt the same coordinator; user/session authorization belongs to the dedicated Web adapter.
- Updater owns release/deployment orchestration. Applications own data schemas, migrations and domain validators. Server Manager owns live server observations; GPU Node Manager owns runtime/GPU lifecycle.
- Use Server Manager as the source of current infrastructure state. Do not infer live state from this roadmap or prior conversations.
- Direct installation targets: AI-side applications v1.0, GPU Node Manager v1.2, Updater v1.0. Existing unmanaged deployments cannot be imported into Updater management. The entry CLI, enrollment action/tools/role and transition evidence are removed. Preserve normal application-owned schema migration, managed updates and recovery. Simple bootstrap/Web setup and managed install/update now share per-app records and Jobs; inspect managed.py, setup.py, recipes.py, docs/RUNNING.md and tests/test_managed.py. Separate source/CI from publication/live acceptance.
- Private CA and client certificates are removed. Owner transport is a local peer-checked Unix socket; the host API binds loopback and retains signed operation authorization. Public coordinator/release traffic uses ordinary HTTPS/system trust. Read docs/TRANSPORT.md; do not reintroduce client PKI. Bootstrap provisions package services/account/local helper, while tunnel/proxy management remains external.
- Release and config/DB/data schema versions are independent. Migration paths are explicit directed edges, not consecutive release numbers.
- Persist step intent/outcomes and verify actual state. Unknown or partially applied outcomes stop; do not blindly retry or assume reverse migration is safe.
- Implement no DB backup, system backup or data restore. Configuration/application data, databases, shared infrastructure and external AI runtimes/models stay outside executable cleanup. Keep current plus one previous only after success; failed/unknown Jobs retain old versions. Do not claim atomic multi-host/group rollback.
- MCP exposes planning, authorized plan execution, progress, release notes and update history. Do not implement arbitrary shell or duplicate Server Manager diagnostics.
- Plans must bind artifacts, targets and preconditions; host execution is least privilege and limited to approved operations.
- Read docs/REVIEW_LOOP_2026-10-08.md before implementing these contracts. Enforce one consumed plan/Job, immutable operation bindings, durable owner maintenance/authority epochs, confirmed predecessor/barrier receipts and local/global finalization. Preserve blockers through linked recovery ownership transfer; normal adapters cannot update protected coordinator/executor roles under aliases.
- CI builds digested artifacts; the separate manual protected signing workflow prepares reviewable release candidates. Hosts normally do not build source. Never clone source directly into /opt; use the connected GitHub integration for private repository work, or authenticated gh on a workstation.
- Public documentation remains portable. Do not copy private hostnames, topology, secrets or deployment-specific paths into product defaults.
- Update PROGRESS.md as work advances. Distinguish documentation, implemented source, tests/CI, releases and live acceptance.
- Current authorization covers Updater implementation, tests/CI, review/correction and merge. Application-specific migrations in other repositories, trust/profile provisioning, release publication and real-host rollout remain separate integration work. Read detailed design, migration, execution/recovery and acceptance documents before changes.

## Current simplified operator flow (2026-10-11)

- Application repositories own their builds/releases/payloads. Do not recreate a central all-app/all-platform candidate build or flat distribution in Updater.
- Catalogs only describe release URLs, digests, settings and compatibility; allow independent repository catalogs in one operator screen. One source failure must not block another source's release check.
- Updater user authentication is removed by explicit user instruction: no administrator creation, setup code, login/session, CLI/MCP token, persistent integration key or grant UI. Do not reintroduce those prerequisites.
- Keep local OS service-account/helper-peer separation, confined installation paths, bounded typed operations, digest verification, preserved settings/data, durable Jobs and side-by-side versions. These are installer mechanics, not end-user authentication.
- Historical signed Core/Owner contracts are separate internal integration mechanisms, not requirements for ordinary install/update. Read the current README, RUNNING, INSTALL and TRANSPORT before using historical design documents.
- Source changes do not claim app-repository release publication or real-host rollout. Published 1.0.3 keeps its former behavior until a new release is prepared.
