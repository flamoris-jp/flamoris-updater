# Dedicated Updater Web design

Date: 2026-10-08. **Dedicated Web implemented in bundled static assets and the coordinator adapter.** Session/CSRF/API behavior is tested; deployment browser/accessibility acceptance remains pending. See [running](RUNNING.md).

## Ownership and deployment

The operator screen belongs to FLAMORIS Updater in this repository. Do not embed it in flamoris-studio, use Studio's database/authentication/session, or require Studio to be available.

Web, CLI and MCP are adapters over one coordinator, its exact-plan authorization, durable Jobs and update history. Web has no second update engine or data-migration authority. Studio is an ordinary update target whose creative UI/data remain Studio-owned.

Serve the Web backend and bundled static assets from the native Updater coordinator distribution. Assets are built in CI and bound to that signed release; no frontend build is performed on a managed host. The core's package remains UI/transport-neutral.

Expose a dedicated operator origin over HTTPS through an approved reverse proxy or coordinator TLS binding. Private hostname, port and proxy bindings are deployment-profile inputs, not hardcoded public defaults. Use same-origin browser APIs; host mTLS and privileged helper sockets are never browser-facing.

Web can remain usable while Studio is stopped or being updated. If the coordinator itself is unavailable, Web, MCP and ordinary CLI operations are unavailable; the separate local recovery CLI/inspector in the independent controller bundle remains the recovery route. Do not imply a second always-available Web control authority.

## Screens and normal operation

| View | Contents / actions |
| --- | --- |
| Overview | Enrolled applications, observed/installed releases and embedded components, pending updates and blocked Jobs |
| Release details | Verified candidate metadata, cumulative notes, restart/migration/recovery conditions and missing history |
| Plan | Exact target/digest, dependencies, affected resources, backup/restore requirements, authorization and blockers |
| Execution | Authorize/execute a valid plan, follow a durable Job and request cooperative cancellation |
| History | Confirmed/unknown steps, final validation, preserved receipts and linked recovery outcomes |

An operator selects targets, requests a plan, reviews the concrete result, authorizes that exact plan, then starts it. Read-only users can inspect permitted summaries; authorization needs an operator role and execution needs scoped action permission.

Web install/enrollment flows use their separate typed plan actions. Do not infer initialization from an empty screen, missing resource marker or inaccessible target.

A Job started by CLI/MCP appears in Web according to actor/target scope; Web-started Jobs are equally inspectable through CLI/MCP. Browser disconnection, refresh or timeout does not cancel or duplicate a Job. Preserve a request key across an uncertain start response and query the admitted Job instead of submitting a new one.

## Independent identity and browser boundary

The dedicated backend owns its operator identities, sessions, role/target mapping and CSRF checks. Initial operator enrollment is provisioned through a protected local administrative flow; there is no shared default password or use of Studio user accounts. Private credential/bootstrap inputs belong to deployment work.

The implementation uses Argon2 and independent persistent identities/session state. Auth state/configuration lives outside replaceable release directories; its schema and grant/revocation compatibility are part of Updater self-update. A candidate or rollback must read current auth/policy state without restoring older accounts, sessions or permissions. Secrets and credential material never enter browser bundles or update manifests.

Browser sessions use protected cookies with Secure/HttpOnly/SameSite policy. Bind mutation/authorization requests to validated session, CSRF and same-origin checks; use POST for effects and do not broaden CORS. Authenticate and enforce role/target scope on every request, including Job/receipt reads. Prevent login guessing with bounded attempts and audited account/session changes.

API/host credentials stay server-side. Opaque IDs are lookup references, not permissions. Grant issuance records the real authenticated operator, exact plan digest, allowed targets/phases and admission deadline in the same authorization model as CLI.

Release notes, errors and evidence summaries are inert escaped/sanitized data. Exclude secrets, backup contents, raw runner output, user media and private diagnostic logs from screen projections. Never turn notes into executable actions or bypasses.

## Self-update and recovery

The normal screen controls application update/install/enrollment Jobs. In v1, Updater self-update and production restoration are started through the protected operator CLI/independent recovery controller described in [execution/recovery](EXECUTION_RECOVERY.md).

Web may show their history/status when the coordinator is available. During coordinator replacement the screen may disconnect; after reconnect it reads the same persisted Job. It cannot replace the independent recovery controller, clear unknown-resource blockers or restore old journals.

## Acceptance and current state

Future Web checks must cover independent Studio downtime, shared CLI/MCP Job visibility, account/role/target isolation, CSRF, inert note rendering, duplicate/lost-response handling, safe cancellation and self-update disconnection/reconnect.

The Web backend, assets, auth store and endpoints are not created by this change. [Roadmap](ROADMAP.md) retains the later implementation phase; [PROGRESS.md](../PROGRESS.md) records the design correction.

## Review corrections

Use the same one-plan/one-Job admission across every adapter: a new browser request key or a second grant cannot execute a consumed plan twice. Account/role/session checks apply before grant issuance and admission. A browser logout does not cancel an already admitted Job; an operator authority revocation is a separate audited action with safe-boundary behavior.

Show reopening/finalizing separately from completed success. A missing gate or blocker-release acknowledgement remains uncertain, even if target health checks succeeded. Safe summaries are paginated under [parser/response budgets](RELEASE_MANIFEST.md), and the UI never constructs a different authorization digest by reserializing a displayed plan.

Only application update/install/enrollment plans can be authorized/executed from normal Web controls. Profile-resolved coordinator/executor aliases cannot bypass the protected CLI/controller handoff restrictions. Recovery verification is a typed read-only child Job; a successful result is not permission to clear the parent's block.
