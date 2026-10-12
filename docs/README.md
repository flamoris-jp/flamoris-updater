# Documentation

For an AI-guided operation, first choose [initial Updater installation](DISTRIBUTION.md) or [Updater self-update](SELF_UPDATE.md). Both guides specify the order, exact current CLI, catalog refresh, completion checks and interrupted-job handling. Do not bootstrap an existing installation.

Use [running](RUNNING.md) for bootstrap/Web/commands, [installation recipes](INSTALL.md) for prebuilt release preparation, [transport](TRANSPORT.md) for access, [MCP/API](MCP_API.md) for typed operations, and [Web](WEB_UI.md) for the operator flow.

[Contracts](CONTRACTS.md), [roadmap](ROADMAP.md) and [progress](../PROGRESS.md) separate implemented source, automated evidence, publication and real-host acceptance. [Implementation review](SIMPLE_REVIEW.md) records current counterexamples and limits.

[Updater self-update](SELF_UPDATE.md) covers supervised Web/manager updates, the retained original supervisor, credential-free MCP reconnection and structured logs visible to AI. [Diagnostic evidence and manual recovery](DIAGNOSTICS.md) explains log/layout readers, offline evidence, and human intervention when Updater itself is stopped.

Older design/review/adoption documents remain historical records. Their former backup/restore, import, client PKI and deployment-preservation requirements are superseded; do not copy their old JSON examples into a new installation. AI initial minimum is 1.0.0, GNM 1.2.0, Updater 1.0.0. External runtimes/models and shared PostgreSQL are not managed by app cleanup.

The [distribution guide](DISTRIBUTION.md) covers release selection, CPU-specific downloads, checksum verification and first bootstrap from the prebuilt bundle, using published 1.0.8 as its fixed example.

