# Contributing

Start with [README](README.md), [AGENTS](AGENTS.md), [design](docs/DESIGN.md) and [progress](PROGRESS.md).

## Current development stage

This repository is documentation-only. [Detailed design draft 1](docs/DETAILED_DESIGN.md) proposes Python 3.12, package boundaries and contracts. No runtime/build/test/CI commands exist yet. Do not implement from a roadmap alone or describe proposed tools as available.

## Change workflow

- Use a focused branch and Pull Request for substantial changes.
- Describe the problem, resulting behavior, ownership boundaries, compatibility and verification.
- Keep portable documentation here; private topology and deployment evidence belong in restricted operational records.
- Update PROGRESS.md when a phase changes. Separate source completion, release and live acceptance.
- Preserve the single-repository Core/wrapper design and management-entry policy.

For documentation changes, review local links, examples, status wording and consistency across files. Runtime work should add meaningful deterministic tests for changed behavior and failure cases. Real-host mutations are not ordinary unit tests.

Before selecting dependencies, inspect existing FLAMORIS shared infrastructure. Core dependencies must remain application- and transport-neutral.

## Scope and reports

Use existing Issue forms for bugs and proposals. Report the current version, phase, expected/actual behavior and sanitized evidence. Never paste secrets, full environment dumps or sensitive user data.

For security-sensitive reports, follow [SECURITY.md](SECURITY.md).

Code is Apache-2.0 unless otherwise stated; document third-party and non-code asset licenses.
