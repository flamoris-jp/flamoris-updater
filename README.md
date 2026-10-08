# FLAMORIS Updater

MCP-enabled installation, updates, application-owned migration orchestration and release management, built on a reusable Core.

**Status: v1 implementation available in source; release publication and real-host acceptance pending.**

Python 3.12向けのCore、Coordinator、Native/Docker実行アダプター、復旧CLI、MCPと専用Web画面を実装しています。署名鍵・実機プロファイル・各アプリの保守／移行契約を用意してから導入します。公開リリースや実機稼働を保証する状態ではありません。

## Responsibility

Updater owns release discovery, trusted artifacts, exact plans, scoped authorization, durable Jobs and update history. Applications own configuration/database/data schemas, migration handlers, maintenance fences, backups and domain validation. Server Manager remains the source of live infrastructure information; GPU Node Manager owns runtime/GPU lifecycle.

Web, CLI and MCP share one coordinator. The **dedicated Updater Web UI** is included here and owns its own authentication/session state. It has no dependency on flamoris-studio, its accounts, database or availability. Human operators can review and authorize updates through Web or CLI; MCP uses the same permission checks. No interface exposes arbitrary shell execution.

## Packages

| Source | Role |
| --- | --- |
| `src/flamoris_update_core` | Strict contracts, schema/dependency planning and host safety graph |
| `src/flamoris_updater` | FLAMORIS entry policy and durable coordinator |
| `src/flamoris_updater_adapters` | SQLite, signatures, bounded execution, recovery, HTTPS/CLI/MCP and Web |
| `src/flamoris_update_migration` | Independently executable runner for application-owned handlers |
| `tests` | Isolated protocol, failure, artifact and recovery tests |
| `scripts` | Build, schema export, release preparation/signing and bundle verification |

## Development setup

Use an authenticated workstation checkout, rather than cloning directly into deployment directories:

```bash
gh auth status
gh repo clone flamoris-jp/flamoris-updater
cd flamoris-updater
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --constraint requirements-runtime.lock -e '.[dev]'
ruff check src tests scripts
ruff format --check src tests scripts
pytest -q
python -m build
python scripts/export_schemas.py --output dist/schemas
python scripts/check_docs.py
```

Authenticate GitHub CLI first when needed. CI runs the checks and builds/verifies indexed Native bundles for **Linux amd64 and arm64**. Managed hosts consume verified artifacts; they do not build source.

## Running

Six installed entry points are available:

```bash
flamoris-updater --help
flamoris-updater-host --help
flamoris-updater-helper --help
flamoris-updater-recovery --help
flamoris-update-migration --help
flamoris-updater-entry --help
```

Follow [running and release procedures](docs/RUNNING.md) for protected configuration, mTLS, identities, Web login, exact-plan authorization and independent recovery. There are no default credentials or production host bindings. Exported schemas and models define the actual accepted JSON fields; design examples with shortened digests remain illustrative.

Coordinator self-update uses a separately installed stable recovery controller and preserves current control/auth/history state. Root helper/executor and recovery-controller replacement require a separate bootstrap maintenance procedure in v1; unsafe self replacement is blocked.

## Management entry

| Target | Agreed baseline | First managed release |
| --- | --- | --- |
| Installed AI-side applications | v0.1 | v1.0 |
| GPU Node Manager | v1.1 | v1.2 |
| Updater | New project | v1.0 |

These are transition targets, not observed live versions. Applications independently migrate and validate entry versions before enrollment. Release labels and config/DB/data schema versions are independent; explicit edges can migrate schema 1 directly to 3.

## Evidence and adoption

[PROGRESS.md](PROGRESS.md) distinguishes source, tests/CI, release and live acceptance. [Implementation review](docs/IMPLEMENTATION_REVIEW.md) records corrected counterexamples and verification limits. Real application owners, key/profile provisioning, release publication and real-host rollout remain [adoption work](docs/ADOPTION.md).

Start with [documentation](docs/README.md), [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Public documentation stays portable; private topology and operational evidence belong in restricted records.

## FLAMORIS and license

FLAMORIS builds creative tools for humans and AI. Commercial use of [Apache-2.0](LICENSE) code is welcome. Software is provided as-is with no guaranteed individual support; third-party dependencies retain their own licenses and metadata in built bundles.

[Organization map](https://github.com/flamoris-jp/.github) · [AI ecosystem](https://github.com/flamoris-jp/flamoris-ai/blob/main/docs/ai-ecosystem.md) · [Shared repository policy](https://github.com/flamoris-jp/flamoris-commons/blob/main/docs/repository-policy.md) · [Support FLAMORIS](https://github.com/sponsors/flamoris-jp)
