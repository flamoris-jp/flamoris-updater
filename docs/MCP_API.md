# Managed Web, MCP and command API

Bootstrap mode exposes fifteen typed tools through credential-free `/mcp` (Streamable HTTP) and `/api/v1/tools/{name}`. With `--base-path /updater`, these endpoints become `/updater/mcp` and
`/updater/api/v1/tools/{name}`. Preserve the configured public path at the proxy;
Host/Origin remain the pure public origin. Web/CLI/MCP call the same facade and root manager. CLI convenience commands construct the same requests; no caller-selected shell/path/source code is accepted.

| Tool | Arguments/purpose |
| --- | --- |
| `updater_catalogs_list` | Registered catalog URLs |
| `updater_catalog_add` | `url`; register one repository catalog |
| `updater_catalog_remove` | `url`; remove source, retaining installations |
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

No login, Bearer token, setup code or integration key is used. Web/CLI/MCP operate through the same local service. The endpoint's configured Host and any supplied Origin are checked; local helper OS-peer checks and strict tool schemas remain. Account/key/grant endpoints have been removed. See [transport](TRANSPORT.md).

Install Jobs end at `awaiting_setup`; after app setup/start, verify to become `succeeded`. Updates progress through recorded download/stage/stop/switch/health/runtime checks. Lost or partial effects become `recovery_required` and are never blindly replayed or followed by old-version cleanup. Reusing a request key returns the same Job; changed arguments conflict. Job results never contain settings/password values.

Internal Core/Owner signed-plan integration models remain separate from the normal endpoint. The MCP catalog advertises only managed tools; callers cannot submit old grants/plans or arbitrary shell commands.
