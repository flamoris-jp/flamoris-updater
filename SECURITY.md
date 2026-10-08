# Security

## Supported state

FLAMORIS Updater is in documentation bootstrap. There is no supported runtime release or security-maintenance version matrix yet. Define that matrix when releases become available.

## Reporting

Do not disclose vulnerabilities, credentials, tokens, private keys, sensitive logs or user data in public Issues.

Use GitHub private vulnerability reporting if it is enabled for this repository. If unavailable, contact a maintainer through an existing private channel to agree on a reporting route before disclosing details. This document does not claim that private reporting is enabled or invent a contact address.

Provide a minimal reproduction, affected version/phase, impact and sanitized evidence. No guaranteed individual support or response time is offered.

## Design requirements

- Verify immutable artifacts and their trusted signatures before deployment.
- Restrict host execution to declared authorized operations; no arbitrary shell MCP tool.
- Keep secret values out of manifests, notes, update history and diagnostics.
- Revalidate authorization/preconditions before execution and prevent duplicate starts.
- Stop on unknown migration outcomes; retain independently readable evidence.
- Require verified recovery conditions before destructive automated updates.

See [design](docs/DESIGN.md) for the accepted direction. These requirements are not claims of implemented controls.
