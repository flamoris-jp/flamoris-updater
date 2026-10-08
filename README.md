# FLAMORIS Updater

MCP-enabled installation, update, migration orchestration, and release management for FLAMORIS, built on a reusable core.

**Status: development — basic design and detailed draft; runtime not implemented.**

## What it is / 何者か

FLAMORIS Updater manages application releases and deployment transitions. A reusable Update Core and a FLAMORIS-specific wrapper live in **this single repository**; a separate core or native repository is not required.

FLAMORISアプリの導入・更新・移行の実行管理・リリース情報を扱います。汎用CoreとFLAMORIS専用ラッパーは、同じリポジトリ内で分離します。

## What it owns / 主な責任範囲

- Installed-release inventory, release discovery, API compatibility and dependency checks.
- Update plans, application/group coordination, bounded host operations and durable execution history.
- Backup/restore verification, application-owned migration execution and post-update acceptance.
- Release notes and an external MCP surface for planning, execution and progress.

These are accepted design goals, **not available tools or commands**.

## Neighboring responsibilities / 責任分界

| Owner | Responsibility |
| --- | --- |
| Updater | Release/deployment orchestration and update history |
| Each application | Configuration, database and persistent-data schemas, migration handlers and domain validation |
| Server Manager | Live server information, service state and diagnostic/log access |
| GPU Node Manager | Runtime/GPU lifecycle and exclusion |
| Human + AI | Failure investigation, recovery decisions and exceptional repair |
| Studio | Planned user-facing update and release-note UI |

Updater does not provide general diagnostic tooling or arbitrary shell execution. Its adapters coordinate with existing lifecycle owners.

## Current status / 現在の状態

This repository contains the project documentation and contributor guidance. There is no executable updater, published release, installer, migration implementation, MCP server or deployment configuration yet.

基本方針と詳細設計案を文書化しています。Python 3.12、Native coordinator／host executor、署名付きManifest、永続Job、Migration契約、復旧、MCPの具体案は [詳細設計](docs/DETAILED_DESIGN.md) を参照してください。ソース・CI・実機設定は未実装で、実機棚卸しや各アプリ固有の移行／保守契約は別工程です。

See [PROGRESS.md](PROGRESS.md) for completed work and [roadmap](docs/ROADMAP.md) for the next phases.

## Management entry versions / 管理開始バージョン

| Target | Agreed baseline | First Updater-managed release |
| --- | --- | --- |
| Currently installed AI-side applications | v0.1 | v1.0 |
| GPU Node Manager | v1.1 | v1.2 |
| FLAMORIS Updater | New project | v1.0 |

These are agreed transition targets, not a claim about current live deployments. Each application independently migrates and validates its environment to the entry version **before** Updater enrollment. GPU Node Manager is not downgraded to v1.0.

Application release versions and configuration/database/data schema versions are independent.

## Architecture

| Planned area | Role |
| --- | --- |
| `core/` | Portable manifest verification, planning, migration contracts, journal, locking and recovery coordination |
| `flamoris/` | FLAMORIS application catalog, deployment profiles, dependency and operating policies |
| `adapters/` | Bounded Docker/Native deployment and external MCP interfaces |
| `docs/` | Accepted direction, detailed draft contracts and review/acceptance records |

Only the documentation area exists today. Planned package boundaries and interfaces are specified in the detailed design; no package is implemented. Core must not depend on the FLAMORIS wrapper, host identities, MCP transport or product UI.

## Getting started

Read [AGENTS.md](AGENTS.md), [design](docs/DESIGN.md), [contract requirements](docs/CONTRACTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

For a workstation with GitHub CLI available:

```bash
gh auth status
gh repo clone flamoris-jp/flamoris-updater
cd flamoris-updater
```

If GitHub CLI is not authenticated, run `gh auth login` first. Use `gh auth setup-git` when Git authentication is needed for subsequent pulls/pushes. Run clone as the authenticated user; do not clone under `sudo` or directly into `/opt`.

There are no build, test or run commands for a runtime yet. Documentation review currently checks local links, consistency with the agreed boundaries and absence of secrets/private topology.

## Documentation and ecosystem

- [Documentation index](docs/README.md)
- [FLAMORIS organization map](https://github.com/flamoris-jp/.github)
- [FLAMORIS AI ecosystem](https://github.com/flamoris-jp/flamoris-ai/blob/main/docs/ai-ecosystem.md)
- [Shared repository policy](https://github.com/flamoris-jp/flamoris-commons/blob/main/docs/repository-policy.md)
- [Security reporting](SECURITY.md)

Public documentation describes portable contracts. Live inventory and private deployment details belong in restricted operational records.

## FLAMORIS

FLAMORIS builds creative tools for humans and AI. Commercial use of Apache-2.0 licensed code is welcome without permission. Software is provided as-is, with no guaranteed individual support.

困ったときはREADME、文書、Issue、テスト、ログ、ソースをあなたのAIと一緒に確認してください。制作環境を支える仕組みを、少しずつ育てています。

[Support FLAMORIS](https://github.com/sponsors/flamoris-jp) — mostly GPU bills.

## License

Code is licensed under [Apache License 2.0](LICENSE), unless otherwise noted. Models, weights, datasets, media and other creative assets may have separate licenses.
