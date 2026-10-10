# Updater Web

The included standalone UI works with no applications and has no Studio/account/database dependency.

1. Enter the printed setup code, create the administrator and select the trusted release catalog. Storage/access paths are selected by bootstrap and displayed.
2. Log in; select an app/release and complete its release-owned settings form. Missing required providers are explicit installation blockers; optional app connections do not force an installation group.
3. Follow durable install status. `awaiting_setup` means executables/services are provisioned without claiming the application is already healthy. Start the app for its own setup, then verify afterward.
4. Update a succeeded installation. Settings/data are reused, progress/history persists independently of the browser, and cleanup occurs only after verification. The current and previous releases are displayed; previous deletion is explicit.
5. Issue a 24-hour Bearer token, or a persistent read-only/read-execute integration key for continuing MCP use. Web operators can rotate/revoke keys; only issuance/rotation shows the secret. Logout does not cancel Jobs.
6. Select a compatible Updater release to update Web/manager through the pinned supervisor. The page reconnects after the temporary outage; keys/settings/history remain. See [self-update and diagnostic evidence](SELF_UPDATE.md).

The frontend binds loopback as an unprivileged service. Exact Host/Origin, bounded requests, CSP, CSRF, HttpOnly/SameSite cookies and HTTPS Secure cookies apply. Local first setup uses literal loopback HTTP, optionally forwarded over SSH; remote public access requires ordinary HTTPS. No private CA/client certificate or application Owner setup is needed. The old explicit-plan UI remains available only with the advanced coordinator configuration.

Structured effect/layout evidence is available through the scoped MCP/API readers; see [diagnostics and manual recovery](DIAGNOSTICS.md). If Updater itself is stopped, use the independent administrator channel described there.
