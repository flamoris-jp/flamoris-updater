# Access and transport

Updater has no application login, account store, setup code, session cookie, Bearer token or integration key. Anyone able to reach the configured endpoint can perform its operations. Access routing belongs to the deployment's local connection/proxy/tunnel; Updater does not configure it.

| Connection | Contract |
| --- | --- |
| Browser/CLI/MCP → Web | No Updater credentials; loopback HTTP or ordinary HTTPS through the configured external connection; exact Host and supplied Origin checks |
| Web → manager | Bounded local Unix socket; Web verifies root UID and manager accepts the service OS UID |
| Manager → catalogs/payloads | Bounded system-trusted HTTPS with checked redirects and recipe file digests |
| Manager → app | Local Docker/systemd and application health/runtime checks |

The listener stays loopback, and bootstrap retains an unprivileged Web OS account and separate root executor. These are execution permissions, not user registration. JSON input validation, byte limits, fixed operations, confined application paths and cross-origin browser rejection remain. No interface accepts arbitrary shell input.

`--public-origin` specifies the exact public origin; `--base-path` places Web/API/MCP below a prefix. The external proxy must preserve Host and path. Forwarded headers cannot change the route boundary. Updater does not issue certificates, open ports or establish a tunnel.

The internal advanced Core/Owner integration still uses signed operation/receipt and local OS-peer contracts. It is not exposed by the normal Web/CLI/MCP. Private GitHub access and app-owned service credentials are independent; removing Updater login does not make private releases public.
