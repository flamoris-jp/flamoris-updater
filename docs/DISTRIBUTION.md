# Installing the Updater v1.0.0 distribution

The release is at <https://github.com/flamoris-jp/flamoris-updater/releases/tag/v1.0.0>.
The two indexed native bundles contain Updater and its Python dependencies; the
system Python interpreter is not bundled. Requires Linux/systemd, **Python 3.12
at `/usr/bin/python3.12`** and administrator privileges. Built/tested on Ubuntu
24.04 amd64/arm64. Windows/macOS and other Python versions are not supported by
these native bundles. Python/venv, Docker, PostgreSQL and HTTPS access provisioning
remain external work.

## Select and verify

- x86_64: `flamoris-updater-1.0.0-linux-amd64.tar.gz`.
- aarch64: `flamoris-updater-1.0.0-linux-arm64.tar.gz`.

Download the selected archive and `SHA256SUMS` from the release into a normal
working directory. GitHub asset downloads redirect; a browser or `curl --location`
handles those redirects. Check the selected archive against the release checksum:

```bash
sha256sum --check SHA256SUMS --ignore-missing
```

The selected archive must be present and report `OK`. Missing files ignored by
this command are other release assets; they do not certify an absent archive.
Trust the release's HTTPS source. Checksums/indexes detect mismatched bytes; they
are not an independent signature or proof of real-host acceptance.

## Initial installation

Choose an unused protected installation directory. The following is an example
for amd64; substitute the arm64 filename on that architecture:

```bash
sudo install -d -m 0755 /opt/flamoris-updater/1.0.0
sudo tar --extract --gzip --file flamoris-updater-1.0.0-linux-amd64.tar.gz --directory /opt/flamoris-updater/1.0.0 --no-same-owner
sudo chmod -R a-w /opt/flamoris-updater/1.0.0
sudo /opt/flamoris-updater/1.0.0/bin/flamoris-updater bootstrap --root /srv/flamoris/apps
```

Use only a verified archive. Do not extract over an existing installation or
clone/build source inside the production directory. Bootstrap refuses existing
Updater state/services; investigate collisions rather than deleting them blindly.

Bootstrap creates:

| Binding | Default |
| --- | --- |
| Web service | `flamoris-updater.service`, dedicated unprivileged account |
| Local manager | `flamoris-updater-manager.service`, root with peer-checked Unix socket |
| Pinned supervisor | `flamoris-updater-supervisor.service`, original executable directory |
| Bootstrap configuration | `/var/lib/flamoris-updater/setup.json` |
| Web / manager state | `/var/lib/flamoris-updater/web` / `/var/lib/flamoris-updater/helper` |
| Applications | `/srv/flamoris/apps` |
| Initial Web | `http://127.0.0.1:8764` |

Keep `/opt/flamoris-updater/1.0.0`: the supervisor remains there after later
self-updates. Bootstrap options `--directory`, `--root`, `--port` and
`--public-origin` select alternate deployment bindings.

## First Web setup and MCP

Open the printed loopback URL locally or via an SSH forward. Enter the printed
one-time code within one hour, create the administrator, and provide the approved
**direct HTTPS application catalog URL**. This Updater release does not supply
application distribution files or an application catalog. Prepare them separately;
bootstrap itself does not require an already running application.

Remote AI access requires a reachable HTTPS endpoint managed by an external
proxy/tunnel. Web's **MCP integration keys** issues a persistent read-only or
read/execute key; store it in the client's protected credential configuration.
The MCP URL is `<public-origin>/mcp`. Never paste keys into public logs/documents.

For ongoing app/self updates, use a catalog whose artifact endpoints return the
file directly: Updater deliberately rejects redirects. A GitHub release download
URL is therefore suitable for this manual download step, but must not be copied
unchanged into an automated update catalog. Direct HTTPS hosting is separate
operator work; this distribution changes no network/download trust policy.

If Updater itself stops, its MCP cannot inspect/recover it. Use an independent
administrator channel, preserve its journals and private diagnostic exports,
and check queued Jobs before service restart. The full guide is
[diagnostics](https://github.com/flamoris-jp/flamoris-updater/blob/v1.0.0/docs/DIAGNOSTICS.md).

Further contracts: [running](https://github.com/flamoris-jp/flamoris-updater/blob/v1.0.0/docs/RUNNING.md),
[application release preparation](https://github.com/flamoris-jp/flamoris-updater/blob/v1.0.0/docs/INSTALL.md).
