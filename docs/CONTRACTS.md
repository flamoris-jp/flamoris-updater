# Current contract index

Source models/exported schemas are authoritative. Historical backup/restore fields and operations are removed rather than accepted/ignored. Unmanaged import and client PKI remain unsupported.

| Contract | Current reference |
| --- | --- |
| Bootstrap, access and services | [Running](RUNNING.md), [transport](TRANSPORT.md), `setup.BootstrapConfig` |
| Catalog, settings and package recipes | [Installation](INSTALL.md), `managed.Catalog` / `Recipe` / exported InstallCatalog |
| Managed jobs and shared interfaces | [MCP/API](MCP_API.md), [Web](WEB_UI.md), `managed.Start` / `Manager` |
| Updater self-update, MCP continuity and logging limits | [Self-update](SELF_UPDATE.md), `self_update.SelfRelease` / `SelfStart` |
| AI-readable effect/layout evidence and manual recovery | [Diagnostics](DIAGNOSTICS.md), `diagnostics.LogPage` / `LayoutRequest` |
| App-owned schema migrations | Core schema graph and standalone migration runner; no backup/restore prerequisite |
| Advanced signed coordinator/Owner | Current source schemas; matching SDK/profiles are separate integration |
| Source, CI and live boundary | [Progress](../PROGRESS.md), [roadmap](ROADMAP.md) |

The previous detailed manifest/execution/review documents are design history and are marked accordingly; their backup/restore examples must not be used as accepted configurations.
