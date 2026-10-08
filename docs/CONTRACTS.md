# Contract design index

**State:** detailed draft 1; no schema loader, protocol implementation or MCP tools exist.

| Contract | Specification |
| --- | --- |
| Core/wrapper, identities and ports | [Detailed design](DETAILED_DESIGN.md) |
| Release JSON fields, signatures/catalog and notes | [Release Manifest](RELEASE_MANIFEST.md) |
| Resource/schema graph, standalone runner and reconciliation | [Migration contract](MIGRATION_CONTRACT.md) |
| Plans, grants, journals, group updates, install/enroll and self recovery | [Execution and recovery](EXECUTION_RECOVERY.md) |
| MCP tools, actor scopes, Jobs, errors and future UI | [MCP and operator API](MCP_API.md) |
| Existing source boundaries and adoption work | [Adoption inventory](ADOPTION.md) |
| Fault and acceptance scenarios | [Acceptance matrix](ACCEPTANCE.md) |

The accepted ownership/entry policy remains in [DESIGN.md](DESIGN.md). Proposed examples and field/tool names are documentation, not executable files or shipped features.

The application-owned pre-entry migration contract remains independently executable in the future. Updater enrollment verifies completion; it does not assume ownership of the legacy transition.

Review and implementation evidence must distinguish draft design, source completion, signed releases and live acceptance. Track actual state in [PROGRESS.md](../PROGRESS.md).
