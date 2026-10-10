# Security

## Supported release boundary

Updater v1.0.x's initial-install distribution targets Linux/systemd with Python
3.12; native binaries are built/tested on Ubuntu 24.04 amd64/arm64. The release
pipeline validates both bundles before publication. CI is not real-host or
external-client certification. No guaranteed individual support is offered.

## Reporting

Do not disclose vulnerabilities, credentials, tokens, signing keys, sensitive logs
or user data in public Issues. Use GitHub private vulnerability reporting if
enabled; otherwise contact a maintainer through an existing private channel to
agree on a route. This document does not assume reporting is enabled or invent
contact addresses. Provide a minimal reproduction, affected version/phase,
impact and sanitized evidence.

## Simple bootstrap and managed operation

Release recipes come from an explicitly configured direct HTTPS source with
system trust. Digests/indexes, exact release/platform bindings, budgets, protected
paths and immutable release mappings constrain executable staging. Initial
GitHub distribution downloads use trusted HTTPS and published SHA-256 checksums;
this distribution is not an independently signed Core catalog.

Web runs unprivileged on loopback. Exact Host/Origin, CSP, Argon2 passwords,
CSRF/session protection and login/request limits apply. Public access needs an
external HTTPS proxy/tunnel. The root manager admits only the Web service's OS
UID through a peer-checked Unix socket. There is no client CA or mTLS setup.
CLI/MCP accept typed operations, not arbitrary shell commands or destinations.
Persistent integration keys store only hashes, carry scoped read/execute authority
without operator grants, and invalidate on owner changes/disablement or revocation.

Intent and outcomes persist before/after effects. Unknown work stops without
replay, rollback or data restoration. Configuration/data/DBs and external runtime
storage remain outside executable cleanup. An independently pinned supervisor
replaces Web/manager only after immutable candidate checks, read-only probes of
both existing journals and binding checks. It does not update itself or migrate
journal schemas. Preserve its initial executable directory.

Structured evidence excludes raw commands/provider output, exceptions, SQL and
secret settings. Private diagnostic mirrors support human inspection during
Updater downtime; Updater MCP itself is unavailable when Web/manager is stopped.
Server Manager remains the live infrastructure observation authority.

## Separate advanced integration

The explicit signed Core/coordinator/Owner route retains exact-byte Ed25519
catalog/manifest verification, purpose-scoped keys, authority epochs and verified
predecessor barriers. Normal adapters cannot replace its protected roles.
Provisioning its signing keys, Owner profiles and application-owned migrations is
separate from simple bootstrap. The protected signing workflow is retained;
initial-install publication does not synthesize signing keys or bypass that route.

Administrators own protected configuration, credentials, clocks, local bindings
and external access. No production credentials or host profiles are shipped.
See [running](docs/RUNNING.md), [diagnostic/manual recovery](docs/DIAGNOSTICS.md),
[distribution](docs/DISTRIBUTION.md) and [current progress](PROGRESS.md).
