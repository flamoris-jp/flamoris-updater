# Communication and Updater bootstrap

## Current certificate-free management transport

Updater no longer requires a private CA or client certificates. Old `tls`,
`registry_tls`, `ca_file`, Owner HTTPS listeners and certificate fingerprint
allowlists are removed configuration contracts, not optional compatibility paths.

| Connection | Current transport and authorization |
| --- | --- |
| Helper → application Owner | Local framed Unix socket; both sides check Linux `SO_PEERCRED` |
| Coordinator → host API | Loopback HTTP, directly or through an authenticated tunnel; helper still verifies signed requests and exact operation scope |
| Host API → root helper | Existing protected Unix socket and allowed peer UIDs |
| CLI / MCP → coordinator | Bearer token; ordinary HTTPS using system trust, or CLI loopback HTTP through a local/tunneled connection |
| Browser → coordinator | Dedicated HTTPS origin, existing account/session/CSRF checks; ordinary server certificate or loopback HTTPS reverse proxy |
| Release/catalog/OCI download | Ordinary HTTPS using system trust; release/catalog signatures remain independent |

Host API configuration has `listen_host` restricted to `127.0.0.1` or `::1`.
For a remote host, provision an authenticated SSH tunnel or equivalent separately;
Updater does not create, authenticate, supervise or reconnect that tunnel. Do not
publish a host API through an unprotected proxy. A loopback listener does not
replace the helper's signed-command authorization.

Native/Docker bindings now use an Owner connection such as:

```json
{
  "socket_path": "/run/example-owner/control.sock",
  "expected_uid": 1000,
  "timeout_seconds": 120
}
```

The Owner server configuration contains `owner` (the unchanged application-owned
configuration), `socket_path`, `socket_group_id` and `allowed_peer_uids`, instead
of network ports and certificate files. Provision the socket parent directory
owned by the Owner service user, with group traversal but no group write or other
access (for example mode `0710`). The server creates its socket with mode `0660`;
its configured group can connect, but only explicitly allowed OS UIDs can dispatch.
The caller checks `expected_uid` before sending a request. The service must remain
independent of the application process during updates. Configure a service-managed
runtime directory so a crashed process's stale socket can be cleaned at restart;
the Owner refuses to overwrite an existing socket/path. Persistent Owner state
belongs outside that runtime directory.

This breaks old Owner/host/client configuration compatibility. Application
repositories currently pin older SDK revisions; coordinated dependency/config
updates and rebuilt application artifacts are still required. This change does
not silently convert those deployments or claim cross-repository/live acceptance.
It also does not remove the existing backup/recovery protocol or complete the
fresh-install-to-update integration.

## How Updater itself is installed today

The repository currently supplies a Python package, five command entry points,
Web assets, schema export and CI builders/verifiers for Linux amd64/arm64 bundles.
It does **not** supply a one-command bootstrap that installs itself, writes working
host/application configs, provisions service users/units or connects a tunnel.
Release publication remains separate from the source build.

For a development checkout, use the authenticated `gh`/Python virtual environment
procedure in [README](../README.md). This installs commands; it does not start a
working deployment. Runtime deployment additionally needs protected configuration,
state paths and execution permissions, service registration, and the existing
operator/token provisioning described in [running](RUNNING.md). External Web/MCP
access additionally needs ordinary HTTPS ingress or a suitable configured tunnel.
The MCP endpoint is `/mcp`; no client certificate is used.

A simpler installation experience would obtain a pinned release package/bundle,
write minimal local configuration, register/start the service and then optionally
connect its Web/MCP ingress. That bootstrap experience is still work to implement;
cloning a repository and connecting a tunnel alone does not perform these steps.
