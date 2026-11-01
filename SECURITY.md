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

## Current bootstrap and managed operation

Release recipes come from explicitly configured repository catalog HTTPS sources
with system trust. Digests/indexes, exact release/platform bindings, budgets,
protected paths and immutable release mappings constrain executable staging. Initial
GitHub distribution downloads use trusted HTTPS and published SHA-256 checksums;
this distribution is not an independently signed Core catalog.

Current source's public managed fetcher follows at most five HTTPS redirects,
confined to the selected initial origin. An exact GitHub Release download URL
may additionally reach `release-assets.githubusercontent.com` over default-port
HTTPS. Each hop is checked before sending; URL credentials, HTTP downgrade,
fragments, traversal, unrelated hosts and ambient authentication/cookies are
refused on the anonymous public path. Final response and expanded-content
budgets, SHA-256/index checks and immutable recipe bindings still apply. The advanced signed/coordinator/registry
fetcher remains strict and does not follow redirects.

Private GitHub Releases use a separate bounded API path after an initial GitHub
404. Existing operator-owned GitHub credentials are sent only to exact
`https://api.github.com` Release endpoints; metadata redirects are rejected and
asset storage requests carry no Authorization or Cookies. Updater does not
provision or persist those credentials. GitHub repository permissions and
application-owned service credentials remain separate from Updater access.
See [private repository access](docs/GITHUB_RELEASES.md).

Downloader behavior belongs to the installed component: ordinary self-update
replaces Web/manager, not the independently pinned supervisor. Older supervisors
do not acquire newer downloader support through a Web/manager update; replacing
one is explicit administrator maintenance. See [self-update](docs/SELF_UPDATE.md).

The current ordinary Web/CLI/MCP flow has no Updater administrator account,
setup code, password login, session cookie, Bearer token or persistent integration
key. Anyone able to reach the configured endpoint can perform its operations;
access routing is owned by the deployment's external connection/proxy/tunnel.
Exact Host and supplied Origin checks are request boundaries, not user
authentication. This matches [README](README.md) and [transport](docs/TRANSPORT.md).

Web runs unprivileged on loopback. CSP, JSON/input validation, streaming byte
limits, fixed typed operations and confined installation paths remain enforced.
Public access uses an externally configured HTTPS proxy/tunnel. The root manager
admits only the Web service's OS UID through a peer-checked Unix socket; Web
verifies the manager's root UID. These are local execution permissions, not
end-user accounts. There is no client CA or mTLS setup. CLI/MCP do not accept
arbitrary shell commands or destinations.

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
