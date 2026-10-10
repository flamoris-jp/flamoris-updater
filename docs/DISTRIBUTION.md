# Installing the Updater v1.0.4 distribution

The release is at <https://github.com/flamoris-jp/flamoris-updater/releases/tag/v1.0.4>.
The two indexed native bundles contain Updater and its Python dependencies; the
system Python interpreter is not bundled. Requires Linux/systemd, **Python 3.12
at `/usr/bin/python3.12`** and administrator privileges. Built/tested on Ubuntu
24.04 amd64/arm64. Windows/macOS and other Python versions are not supported by
these native bundles. Python/venv, Docker, PostgreSQL and HTTPS access provisioning
remain external work.

## Select and verify

- x86_64: `flamoris-updater-1.0.4-linux-amd64.tar.gz`.
- aarch64: `flamoris-updater-1.0.4-linux-arm64.tar.gz`.

Download the selected archive and `SHA256SUMS` from the release into a normal
working directory under `~/tmp/`. Before generating host-specific commands,
confirm the working directory, protected installation destination and application
root with the operator. Prepare Python, privileges, HTTPS routing,  and the direct HTTPS catalog URL before starting. No GitHub token is needed for this public distribution. GitHub asset downloads redirect; a browser or `curl --location`
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
sudo install -d -m 0755 /opt/flamoris-updater/1.0.4
sudo tar --extract --gzip --file flamoris-updater-1.0.4-linux-amd64.tar.gz --directory /opt/flamoris-updater/1.0.4 --no-same-owner
sudo chmod -R a-w /opt/flamoris-updater/1.0.4
sudo /opt/flamoris-updater/1.0.4/bin/flamoris-updater bootstrap --root /srv/flamoris/apps
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

Keep `/opt/flamoris-updater/1.0.4`: the supervisor remains there after later
self-updates. Bootstrap options `--directory`, `--root`, `--port` and
`--public-origin` select alternate deployment bindings. `--base-path /updater`
serves Web, API and MCP below that prefix. Keep `--public-origin` as a pure
origin (for example `https://updater.example.invalid`); do not include the path.

## Catalog screen and MCP in current source

Open the printed URL and register each repository's catalog. Current source needs no setup code, administrator, login or MCP key. MCP is `<public-origin><base-path>/mcp`. External proxy/tunnel access is configured separately. Application repositories publish their own catalogs and payloads.

Version 1.0.4 removes Updater account/code/key setup. Published v1.0.3 retains
its former workflow; use its existing screen to register the self-update catalog
and update, rather than rerunning bootstrap. The new Release asset is
`https://github.com/flamoris-jp/flamoris-updater/releases/download/v1.0.4/catalog.json`.
It declares 1.0.3 as the compatible predecessor and describes only Updater.
Application catalogs and artifacts remain in their owning repositories.
Publication success and actual-host acceptance must be checked separately.

Version 1.0.4 supports at most five checked same-origin HTTPS redirects and an
exact GitHub Release-to-`release-assets.githubusercontent.com` exception for
catalogs, app payloads and supervisor bundles; see [installation](INSTALL.md).
The earlier 1.0.1 package rejects automated-download redirects. Version 1.0.4
also prevents privileged launcher imports from writing unindexed bytecode caches;
1.0.2 lacks that packaging correction. Existing 1.0.1
installations require explicit administrator maintenance of all three services,
including the pinned supervisor, with current Job/journal/binding inspection.
Replacing Web/manager alone leaves the old supervisor downloader. Preserve the
original runtime and all control records; do not run initial bootstrap over an
existing installation. Publication does not certify real-host maintenance.

If Updater itself stops, its MCP cannot inspect/recover it. Use an independent
administrator channel, preserve its journals and private diagnostic exports,
and check queued Jobs before service restart. The full guide is
[diagnostics](https://github.com/flamoris-jp/flamoris-updater/blob/v1.0.4/docs/DIAGNOSTICS.md).

Further contracts: [running](https://github.com/flamoris-jp/flamoris-updater/blob/v1.0.4/docs/RUNNING.md),
[application release preparation](https://github.com/flamoris-jp/flamoris-updater/blob/v1.0.4/docs/INSTALL.md).

## HTTPS below a public path

Bootstrap with `--public-origin https://updater.example.invalid --base-path /updater`
when the chosen public URL is `https://updater.example.invalid/updater/`. Configure
the external proxy to preserve both the original path and public Host. For nginx
on the same host, the location inside an already secured HTTPS server is:

```nginx
location /updater/ {
    proxy_pass http://127.0.0.1:8764;
    proxy_set_header Host $host;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
location = /updater {
    proxy_pass http://127.0.0.1:8764;
    proxy_set_header Host $host;
}
```

The absence of a trailing slash on `proxy_pass` is intentional: do not strip
`/updater`. Updater supplies the canonical `/updater/` redirect. Forward browser Origin without substituting a loopback Origin. Updater does not trust forwarded-prefix headers. Its listener
remains loopback-only; a proxy on another host needs an independently secured
on-host relay, not direct LAN access to that listener. Certificates, proxy ACLs,
relay authentication and reachability are external prerequisites.
