# Documentation

Use [running](RUNNING.md) for bootstrap/Web/commands, [installation recipes](INSTALL.md) for prebuilt release preparation, [transport](TRANSPORT.md) for access, [MCP/API](MCP_API.md) for typed operations, and [Web](WEB_UI.md) for the operator flow.

[Contracts](CONTRACTS.md), [roadmap](ROADMAP.md) and [progress](../PROGRESS.md) separate implemented source, automated evidence, publication and real-host acceptance. [Implementation review](SIMPLE_REVIEW.md) records current counterexamples and limits.

[Self-update and logging review](SELF_UPDATE.md) covers independent supervisor updates, persistent MCP keys, client reconnection and the structured logs currently visible to AI. [Diagnostic evidence and manual recovery](DIAGNOSTICS.md) explains log/layout readers, offline evidence, and human intervention when Updater itself is stopped.

Older design/review/adoption documents remain historical records. Their former backup/restore, import, client PKI and deployment-preservation requirements are superseded; do not copy their old JSON examples into a new installation. AI initial minimum is 1.0.0, GNM 1.2.0, Updater 1.0.0. External runtimes/models and shared PostgreSQL are not managed by app cleanup.

The [v1.0.0 distribution guide](DISTRIBUTION.md) covers release assets, checksum verification and bootstrap from the prebuilt bundle.
