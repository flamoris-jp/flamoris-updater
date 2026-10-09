# Source integration inventory

This file records historical source inspection; it is not an unmanaged-deployment
import procedure. The import feature and its work packages are removed. Current
source behavior is defined by [running](RUNNING.md) and [progress](../PROGRESS.md).

## Historical inspected source

| Repository | Pinned source checked | Design implication |
| --- | --- | --- |
| [Studio](https://github.com/flamoris-jp/flamoris-studio/blob/d03028df892f7b1dc658534d22abaffcc34a5134/pyproject.toml) | d03028d | Python >=3.12; owns its application DB/Alembic and creative user sessions; an update target, not the Updater UI owner |
| [Agent](https://github.com/flamoris-jp/flamoris-ai-agent/blob/d5dd2e0a922e08e3054a71defb7f79b40d754a28/pyproject.toml) | d5dd2e0 | Python >=3.11; own SQL migration history and conversation data |
| [Controller](https://github.com/flamoris-jp/flamoris-generation-controller/blob/2e85caac885a84a851d92a7864e7b94c4f95ad86/docs/MIGRATION.md) | 2e85caa | Importable shared authority hosted with Generation; recipes/assets/unknown reservations must be preserved |
| [Hub](https://github.com/flamoris-jp/flamoris-mcp-hub/blob/e74f2cfa45e5ea57ec0996c6d7a6e83c5c4b4aee/pyproject.toml) | e74f2cf | Python >=3.11; external routing/catalog, not application schema owner |
| [GPU Node Manager](https://github.com/flamoris-jp/flamoris-gpu-node-manager/blob/2f55fb74b986b7fa9c0eceb00cab2bd94187fdca/docs/ARCHITECTURE.md) | 2f55fb7 | Existing manager/lock owns lifecycle; current source package version 1.0.0 differs from the agreed baseline release label |
| [AI Runtime](https://github.com/flamoris-jp/flamoris-ai-runtime/tree/e2f4ff709246922674d99344e02c8ce364f9e8f2) | e2f4ff7 | Native C++ project; managed deployment is not inferred from source presence |
| [MCP Core](https://github.com/flamoris-jp/flamoris-mcp-core/blob/a21e82519e94d923503cb64f3c10e6289f22e995/README.md) | a21e825 | .NET library; reuse principles rather than importing it into Python |
| [Logging](https://github.com/flamoris-jp/flamoris-logging/blob/c2ef62c257c5b9a1bb76a8960f1c805630c1f320/README.md) | c2ef62c | .NET library; no direct Python package reuse |
| [AI coordination](https://github.com/flamoris-jp/flamoris-ai/blob/ab16166d0711b0c7567c188aabedfe36dd4d27bc/PROGRESS.md) | ab16166 | Source/live evidence is explicitly separated; operational release history is not a current health probe |

These pins describe the inspected source at that checkpoint, not current live
hosts. Use Server Manager for actual infrastructure observations. Application
Owners and the common migration runner remain normal update infrastructure.

## Remaining integration

Prepare usable application artifacts, first-install configuration/setup and a
single installation record/layout consumed by later updates. No legacy baseline
version, transition receipt or import operation is a prerequisite. Public release
and live acceptance are separate outcomes; no host operation is performed here.
