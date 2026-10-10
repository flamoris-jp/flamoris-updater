# Access and transport

Private CA, per-owner client certificates, certificate fingerprints and client TLS credential fields are removed.

| Connection | Simple bootstrap mode |
| --- | --- |
| Browser → Web | Literal loopback HTTP for first/local setup, or ordinary HTTPS at a separately configured proxy/tunnel; account/session/CSRF and exact Host/Origin |
| CLI/MCP → Web | Short-lived token or persistent revocable integration key; ordinary HTTPS/system trust or literal loopback HTTP |
| Web → root manager | Framed bounded Unix socket; Web verifies root UID, root accepts only provisioned Web UID |
| Manager → releases | Ordinary system-trusted HTTPS; selected recipe/file digests bind execution |
| Manager → app | Local Docker/systemd and local app health contract; no pre-running Owner prerequisite |

Bootstrap provisions the dedicated service account, private Web/helper journals and units. Web is unprivileged and listens only on loopback. systemd owns `/run/flamoris-updater` with protected group traversal and removes the stale socket on restart. Local HTTP uses distinct host cookies; HTTPS uses `__Host-` Secure cookies. Host/Origin checks and CSRF apply in both modes; plaintext remote origins are rejected. The setup code is expiring and consumed after first setup.

An SSH forward can expose loopback setup to an administrator without a certificate. An ordinary HTTPS proxy/tunnel can expose the configured public origin later; preserve its public Host. Updater does not start/manage/authenticate/reconnect that tunnel or issue public server certificates. See [running](RUNNING.md).

The explicit advanced coordinator path retains signed host operation/receipt authorization over loopback/tunnels and local OS-peer Owner sockets. Its public endpoint uses ordinary HTTPS and matching SDK/profile contracts. It no longer has snapshot/restore operations. Current application source pins for that optional Owner path still need matched rebuilds; no old installation/config/state is converted implicitly. Simple bootstrap does not depend on its five key sets or application Owner services.
