# Repository catalogs — 2026-10-11

The application repositories own their builds, Releases, payloads and installer definitions. This directory contains reference metadata only. The dated catalog is an initial-install snapshot; it does not copy or rebuild any application payload.

Published initial-install catalog:

`https://raw.githubusercontent.com/flamoris-jp/flamoris-updater/main/catalogs/flamoris-20261011.json`

It includes Updater 1.0.4 with an explicit 1.0.3 self-update predecessor, and the six runnable services for Linux amd64/arm64. An unconfigured 1.0.3 can use this catalog during its existing setup. An already configured 1.0.3 needs the [one-time catalog switch](../docs/UPGRADE_103.md), then selects self-update from its existing screen. After updating, register the repository's `latest` catalog URLs for independently published future versions. The dated snapshot remains immutable; remove its registration if no longer needed. Registration removal preserves installed applications and their data/history.

| Repository | Published release | Catalog for future release checks |
| --- | --- | --- |
| [Updater](https://github.com/flamoris-jp/flamoris-updater/releases/tag/v1.0.4) | 1.0.4 | `https://github.com/flamoris-jp/flamoris-updater/releases/latest/download/catalog.json` |
| [GPU Node Manager](https://github.com/flamoris-jp/flamoris-gpu-node-manager/releases/tag/v1.2.1) | 1.2.1 | `https://github.com/flamoris-jp/flamoris-gpu-node-manager/releases/latest/download/catalog.json` |
| [AI Agent](https://github.com/flamoris-jp/flamoris-ai-agent/releases/tag/v1.0.1) | 1.0.1 | `https://github.com/flamoris-jp/flamoris-ai-agent/releases/latest/download/catalog.json` |
| [Generation MCP](https://github.com/flamoris-jp/flamoris-generation-mcp/releases/tag/v1.0.1) | 1.0.1 | `https://github.com/flamoris-jp/flamoris-generation-mcp/releases/latest/download/catalog.json` |
| [Intelligence MCP](https://github.com/flamoris-jp/flamoris-intelligence-mcp/releases/tag/v1.0.1) | 1.0.1 | `https://github.com/flamoris-jp/flamoris-intelligence-mcp/releases/latest/download/catalog.json` |
| [MCP Hub](https://github.com/flamoris-jp/flamoris-mcp-hub/releases/tag/v1.0.1) | 1.0.1 | `https://github.com/flamoris-jp/flamoris-mcp-hub/releases/latest/download/catalog.json` |
| [Studio](https://github.com/flamoris-jp/flamoris-studio/releases/tag/v1.0.1) | 1.0.1 | `https://github.com/flamoris-jp/flamoris-studio/releases/latest/download/catalog.json` |

[Controller 1.0.0](https://github.com/flamoris-jp/flamoris-generation-controller/releases/tag/v1.0.0) is published as a library in its own repository. Generation MCP embeds the fixed Controller dependency and hosts the shared runtime. It is not a seventh daemon or a second owner of the same output root.

All repository source/package CI and both native platform build/profile checks succeeded, as did the Release publication jobs. `verification-20261011.json` records actual public catalog downloads, GitHub-reported payload hash agreement and bounded opening of each platform's main payload transfer. Complete payload bytes were verified in the owning repository's publisher; the later public checks did not redownload every complete image. No host install/update or provider/model call was performed.

## Initial configuration

- Use Linux/systemd, Python 3.12 and the required Docker/PostgreSQL access.
- Update Updater 1.0.3 to 1.0.4 through its existing installation, retaining its original supervisor and control state. Do not rerun initial bootstrap.
- Install GPU Node Manager Native. Add deployment-owned runtime profiles for the already installed services; installation does not start a GPU runtime.
- Install the other services individually on their chosen hosts. Agent and Studio require a PostgreSQL administrator connection for dedicated new DBs. Existing DB/role names stop before initialization.
- Supply the actual ComfyUI/model roots and service endpoints/tokens through private local settings. Studio calls the Controller HTTP API and Agent HTTP API; its internal path does not go through Hub/MCP.
- Complete Agent identity/personality/principal/model registration and Studio user configuration. Configure Hub upstream catalogs, runtime profiles and optional Speech/Music providers as needed. Published binaries and liveness do not certify these domain prerequisites.

Future app updates must publish an explicit compatible predecessor and app-owned migration integration when schemas change. These initial app recipes intentionally claim no unverified upgrade from the former centralized candidates.
