# Current source and remaining integration

| Area | Implemented source | Separate evidence/work |
| --- | --- | --- |
| Updater bootstrap | Package/bundle launcher, dedicated Web account, two units, local peer helper, empty-app startup | Install reviewed artifact on a disposable/real host |
| Web first setup | Expiring code, administrator, release source, displayed storage root | Browser/access/proxy deployment acceptance |
| Per-app installation | Recipe settings, prebuilt Native/Docker, app-owned new DB initialization, `awaiting_setup` → verification | Real first setup for every app/external connection |
| Updates | Same registry/Jobs, staged code, retained settings/data, declared compatibility/dependencies, switch/health | Real supported next-release acceptance |
| Web/MCP/CLI | Same eight managed operations and durable status/history | Client/access operational acceptance |
| Old versions | Current plus one previous; post-success executable/cache cleanup and explicit previous deletion | Actual host capacity/ownership verification |
| Data changes | Standalone app-owned migration runner; no backup/restore prerequisite | App-specific new schema handlers and matching Owner SDK when needed |
| Releases | Exact candidate builds, portable catalog generator, CI/manual artifacts | Maintainer review/distribution/publication |

No DB/system backup, unmanaged adoption, private CA or per-owner client certificate feature remains. PostgreSQL/external runtimes/models and Server Manager remain independent. Generation Controller is embedded in the Generation package.

Publication and full-host certification are not prerequisites for controlled first-install tests. CI/source evidence must not be called live deployment. The old detailed design documents preserve design history; [running](RUNNING.md), [installation](INSTALL.md), exported models and [progress](../PROGRESS.md) define current behavior. Updater/root-helper self replacement is a separate reviewed maintenance operation, not app executable cleanup.
