# FLAMORIS Updater

必要なFLAMORISアプリを選んでインストールし、以後は設定とデータを引き継いで更新する、独立したWeb・MCP・CLI管理サービスです。

**Source status:** simple bootstrap/setup/install/update is implemented and tested; release publication and real-host acceptance are separate. Read [progress](PROGRESS.md) for exact evidence. Existing unmanaged applications cannot be imported.

## Installation and use

1. Install a reviewed prebuilt Updater wheel/runtime or indexed Native bundle (Linux amd64/arm64, Python 3.12, systemd).
2. Run `sudo /absolute/path/bin/flamoris-updater bootstrap`. It provisions a dedicated Web account, two systemd services, private journals and a peer-checked local helper. It prints the Web URL and an expiring setup code.
3. Open Web setup, enter the code, create the administrator, and select the ordinary HTTPS release catalog. `--root`, `--directory`, `--port` and `--public-origin` select deployment paths/access during bootstrap; no application JSON profile or private CA is required.
4. Select each application and enter its displayed settings. Installation stages its package and services, then reports **initial setup pending**. Start it for its own setup, and verify afterward.
5. Update an installed app: download/stage beside the old version, reuse installed settings/data, stop/switch/start and verify. Successful updates keep **current plus one previous version**; older executable versions are removed. Failed/unknown updates retain old versions and require inspection.

[Running](docs/RUNNING.md) has executable commands, [installation](docs/INSTALL.md) the release recipe contract, and [transport](docs/TRANSPORT.md) the access boundary. A checkout plus a tunnel alone does not install the package or services. An authenticated tunnel/proxy is configured separately; Updater does not manage it.

## Boundaries

Updater implements **no database backup, system backup or data restore**. Existing backup services remain independent. Cleanup excludes configuration, databases, application data/outputs, shared PostgreSQL, external AI runtimes and models. Applications own first setup, schema migration and domain behavior; Server Manager owns infrastructure observations and GPU Node Manager owns runtime lifecycle.

The simple local update path accepts explicitly declared schema/settings-compatible predecessors; it does not run an invented reverse migration. The standalone application migration runner remains available. Owner-driven migration and the older signed multi-host coordinator are advanced integration paths with their own matching profiles/SDK. They are not bootstrap prerequisites or a second registry for a simple installation.

Six deployment units are supported: AI Agent, Studio, Intelligence MCP, Generation MCP, MCP Hub and GPU Node Manager. Generation Controller is embedded in Generation's prebuilt image. AI initial minimum is 1.0.0, GNM 1.2.0, Updater 1.0.0; later compatible releases are allowed. Only declared real provider dependencies constrain installation order. No model/runtime is installed.

Web, commands and eight managed MCP tools share the same authority, root executor, application records and durable Jobs. CLI/MCP use Bearer tokens created in Web; Web uses independent password/session/CSRF checks. Public connections use ordinary HTTPS/system trust. The public Web process is unprivileged and binds loopback; only its OS UID can call the privileged local helper. No interface accepts a shell command or caller-selected file destination.

## Release preparation and development

Release maintainers build candidates and portable recipes in CI/workstations, then distribute artifacts/catalog over ordinary HTTPS. Operators enter settings through Web rather than writing profiles. Source verification or a controlled candidate test can run before publication/full-host acceptance. Nothing in these commands automatically publishes a release.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --constraint requirements-runtime.lock -e '.[dev]'
ruff check src tests scripts
ruff format --check src tests scripts
pytest -q
python -m build
python -m build packages/update-core --outdir dist/sdk
python scripts/export_schemas.py --output dist/schemas
python scripts/check_docs.py
```

Core, FLAMORIS policy, adapters, migration runner, Web assets and tests remain in this repository. Core has no MCP/Studio/FLAMORIS dependency. Application schema/config compatibility is intentionally changed from the historical backup/restore contracts; old plans and Owner configs are not silently converted. Existing application SDK pins for the advanced Owner path require separate matched rebuilds. The simple path does not require a running Owner or preconfigured application.

## License

Apache License 2.0. External applications, models and media retain their own licenses.
