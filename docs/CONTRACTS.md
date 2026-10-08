# Contract design index

**State:** reviewed design with executable v1 source/models, schema export and fourteen MCP tools. See [running](RUNNING.md) and [implementation review](IMPLEMENTATION_REVIEW.md) for exact supported behavior and remaining adoption gates.

| Contract | Specification |
| --- | --- |
| Core/wrapper, identities and ports | [Detailed design](DETAILED_DESIGN.md) |
| Release JSON fields, signatures/catalog and notes | [Release Manifest](RELEASE_MANIFEST.md) |
| Resource/schema graph, standalone runner and reconciliation | [Migration contract](MIGRATION_CONTRACT.md) |
| Plans, grants, journals, group updates, install/enroll and self recovery | [Execution and recovery](EXECUTION_RECOVERY.md) |
| MCP tools, actor scopes, Jobs and errors | [MCP and operator API](MCP_API.md) |
| Dedicated Updater Web, independent login/session and operator flow | [Web UI](WEB_UI.md) |
| Existing source boundaries and adoption work | [Adoption inventory](ADOPTION.md) |
| Fault and acceptance scenarios | [Acceptance matrix](ACCEPTANCE.md) |

The accepted ownership/entry policy remains in [DESIGN.md](DESIGN.md). Shortened digest examples remain illustrative; actual source models and exported schemas define accepted fields/tool names.

The application-owned pre-entry migration contract uses the independently executable common runner with application-owned handlers. Updater enrollment verifies completion; it does not assume ownership of the legacy transition.

Review and implementation evidence must distinguish draft design, source completion, signed releases and live acceptance. Track actual state in [PROGRESS.md](../PROGRESS.md).

The [2026-10-08 review/correction loop](REVIEW_LOOP_2026-10-08.md) records the reviewed contract changes and their future acceptance cases. It is documentation evidence only.
