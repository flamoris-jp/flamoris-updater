# Security

## Supported state

The v1 source implementation has deterministic security/failure tests and CI. No public runtime release or real-host certification is claimed yet. A supported release/version matrix must accompany actual publication.

## Reporting

Do not disclose vulnerabilities, credentials, tokens, signing keys, sensitive logs or user data in public Issues. Use GitHub private vulnerability reporting if enabled; otherwise contact a maintainer through an existing private channel to agree on a route. This document does not assume that reporting is enabled or invent a contact address.

Provide a minimal reproduction, affected version/phase, impact and sanitized evidence. No guaranteed individual response time is offered.

## Implemented boundaries

Exact-byte Ed25519 verification uses pinned keys separated by application/domain and purpose. Catalog replay/equivocation and immutable release mappings are checked. Artifact staging verifies digest/platform/index, bounds downloads/extraction and rejects unsafe archive entries. Host admission independently enforces plan coverage, profile allowlists, signed predecessor barriers, local claims and durable intent.

Authorization and target scope are checked at admission and later phases. Web has Argon2 passwords, Secure/HttpOnly/SameSite cookies, CSRF/Origin checks, bounded login attempts and inert text rendering. Host traffic requires mTLS and a peer-checked local helper socket. CLI/MCP cannot select shell commands, mount paths or execution privileges.

Unknown effects retain blockers and tombstones. Recovery requires positively reconciled fences, original verified snapshots and linked ownership transfer. Coordinator self-update preserves current control/auth state and advances authority epochs; incompatible candidates stop. Executor/helper/controller self replacement is blocked in v1.

## Deployment requirements

Secure signing/recovery keys, protected configuration and ancestor directories, synchronized clocks, independent lifecycle owners, isolated restore credentials and correct writer/resource inventory are operator responsibilities. `clock_healthy` is a provisioned assertion, supplemented by runtime wall/monotonic drift checks; it is not an OS time-synchronization probe. Root helper and Docker daemon privileges require separately reviewed local bindings. No production credentials/default host profiles are shipped.

See [running](docs/RUNNING.md), [implementation review](docs/IMPLEMENTATION_REVIEW.md) and [live acceptance](docs/ACCEPTANCE.md). Automated tests use isolated owners/command adapters and do not establish real systemd, Docker, TLS deployment or application-domain safety.
