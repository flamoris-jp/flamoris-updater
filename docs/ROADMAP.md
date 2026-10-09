# Roadmap

The existing update/recovery implementation remains. Unmanaged-deployment import
has been removed, including its CLI, registration APIs, authority role and
transition evidence. No baseline transition or import work package remains.

| Area | Current source | Remaining work |
| --- | --- | --- |
| Release packages and verification | Models, artifacts, signatures, catalog and bundle tooling | Usable application candidates and distribution |
| Managed updates | Planning, Native/Docker operations, application Owners | Connect new installation state/layout to subsequent updates |
| Application schema changes | Common migration runner | Application-specific handlers; current Owner rejects schema changes |
| First installation and setup | Separate work; not supplied by this removal | App selection, first setup and per-app installation records |
| CLI/Web/MCP | Shared coordinator; twelve MCP tools | Connect the simple installation/update flow |
| Recovery | Durable journals and protected controller | Verify supported recovery against real installations |

Public release and full real-host acceptance are outcomes of integration work,
not prerequisites for beginning controlled installation tests. This change does
not publish a release or modify an actual host. See [progress](../PROGRESS.md).
