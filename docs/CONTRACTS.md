# Contract design index

**State:** reviewed design with executable v1 source/models, schema export and twelve MCP tools. See [running](RUNNING.md) and [implementation review](IMPLEMENTATION_REVIEW.md) for exact supported behavior and remaining integration work.

| Contract | Specification |
| --- | --- |
| Local transport, removed certificate fields and bootstrap limits | [Communication](TRANSPORT.md) |
| Core/wrapper, identities and ports | [Detailed design](DETAILED_DESIGN.md) |
| Release JSON fields, signatures/catalog and notes | [Release Manifest](RELEASE_MANIFEST.md) |
| Resource/schema graph, standalone runner and reconciliation | [Migration contract](MIGRATION_CONTRACT.md) |
| Plans, grants, journals, group updates, install and self recovery | [Execution and recovery](EXECUTION_RECOVERY.md) |
| MCP tools, actor scopes, Jobs and errors | [MCP and operator API](MCP_API.md) |
| Dedicated Updater Web, independent login/session and operator flow | [Web UI](WEB_UI.md) |
| Source integration boundaries | [Source inventory](ADOPTION.md) |
| Fault and acceptance scenarios | [Acceptance matrix](ACCEPTANCE.md) |

The accepted ownership/version policy remains in [DESIGN.md](DESIGN.md). Shortened digest examples remain illustrative; actual source models and exported schemas define accepted fields/tool names.

The common migration runner remains available for application-owned schema changes. Existing unmanaged deployment import and pre-entry transitions are not supported; no enrollment action or evidence contract remains.

Review and implementation evidence must distinguish draft design, source completion, signed releases and live acceptance. Track actual state in [PROGRESS.md](../PROGRESS.md).

The [2026-10-08 review/correction loop](REVIEW_LOOP_2026-10-08.md) records the reviewed contract changes and their future acceptance cases. It is documentation evidence only.
