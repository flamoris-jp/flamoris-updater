# Managed Web, MCP and command API

Bootstrap mode exposes twelve typed tools through authenticated `/mcp` (Streamable HTTP) and `/api/v1/tools/{name}`. With `--base-path /updater`, these endpoints become `/updater/mcp` and
`/updater/api/v1/tools/{name}`. Preserve the configured public path at the proxy;
Host/Origin remain the pure public origin. Web/CLI/MCP call the same facade and root manager. CLI convenience commands construct the same requests; no caller-selected shell/path/source code is accepted.

| Tool | Arguments/purpose |
| --- | --- |
| `updater_managed_log_get` | `application_id`, `job_id`, optional `after`/`limit`; bounded structured effect timeline |
| `updater_managed_layout_get` | `application_id`, optional `job_id`; recorded current/candidate/previous deployment layout |
| `updater_apps_list` | Optional `refresh`; available releases/settings, per-app installation/current/previous |
| `updater_install` | `application_id`, `release`, `request_key`, optional settings; durable install Job |
| `updater_update` | Same identity/key, no changed settings; explicitly compatible update Job |
| `updater_install_start` | `application_id`; start staged app for its own setup |
| `updater_install_complete` | `application_id`; verify initial app health/runtime and complete record |
| `updater_previous_delete` | `application_id`; delete retained previous executables without changing config/data |
| `updater_managed_job_get` | `job_id`; durable progress/result/retained candidate/blocker |
| `updater_managed_history` | Recent 100 durable Jobs |
| `updater_self_status` | Current/previous Updater, bootstrap support and available self releases |
| `updater_self_update` | `release`, `request_key`; independently supervised Web/manager update |

Use a Web-issued Bearer token for CLI/MCP. Ordinary tokens expire after 24 hours. For continuing automation, the Web administrator can create a persistent integration key with read-only or read/execute access, rotate it or revoke it. It cannot issue keys or grants. Changing/disabling its owner invalidates it. Web login is independent of Studio; passwords use Argon2, session mutations require same Origin and CSRF. Target/role permissions are checked before IPC. Setup requires the expiring bootstrap code and is unavailable after completion.

Key management is password-session-only: `GET/POST /api/v1/integrations`, `POST /api/v1/integrations/{id}/rotate` (label and execute), and `POST /api/v1/integrations/{id}/revoke` (empty body). Mutations require Origin/CSRF. Issuance/rotation returns the secret once; lists omit it. MCP has no credential issuance or arbitrary log-file download tool. The two scoped diagnostic readers expose secret-free typed evidence. See [evidence and manual recovery](DIAGNOSTICS.md).

Install Jobs end at `awaiting_setup`; after app setup/start, verify to become `succeeded`. Updates progress through recorded download/stage/stop/switch/health/runtime checks. Lost or partial effects become `recovery_required` and are never blindly replayed or followed by old-version cleanup. Reusing a request key returns the same Job; changed arguments conflict. Job results never contain settings/password values.

The exported combined catalog includes separate older signed-plan integration tools for explicit advanced coordinator configurations; that endpoint advertises only its supported twelve tools. They do not form a bootstrap dependency or import managed records. See [running](RUNNING.md) and actual `inputs`/`managed` models for strict schemas.
