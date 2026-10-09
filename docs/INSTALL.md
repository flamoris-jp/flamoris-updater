# Release recipes and direct installation

The normal operator flow is [running](RUNNING.md): bootstrap, Web setup, select an app, first setup, verify, then update through the same records. It needs no pre-running app, application Owner, DB backup, system backup or client certificates.

## Maintainer-owned inputs

`scripts/build_initial_candidate.py` builds immutable Docker archives or GNM offline wheelhouses from exact reviewed source commits. It validates package/image/component versions and writes `candidate.json` with platform, image ID, file digests and source revision. Initial defaults are AI 1.0.0 / GNM 1.2.0. `--revision`, `--version` and repeated `--compatible-from` support later explicitly compatible releases. These arguments are maintainer/CI inputs; caller APIs do not accept commands/source revisions.

```bash
python scripts/build_initial_candidate.py --application flamoris-generation-mcp --platform linux/amd64 --output dist/generation
python scripts/build_install_catalog.py --candidate dist/generation/candidate.json https://releases.example.invalid/generation --output dist/catalog.json
```

Distribute that catalog and its candidate files at the selected direct HTTPS locations (no credential/client certificate or implicit registry login). The source example is illustrative, not an available release. The manual candidate workflow builds reviewable artifacts for all six units/amd64/arm64; it does not publish them. Controlled CI uses disposable candidates before publication.

Generated recipes describe actual app environment fields, new database initialization and program/data layout. Operator choices and generated credentials are private local settings; they are not embedded in public candidates. Agent applies its own schema/migration SQL to a newly-created dedicated DB; Studio runs its own image Alembic. Neither operation touches existing DBs or creates backups. Users supply the PostgreSQL admin connection and a host reachable from both manager and app; unknown/occupied DB/role names stop before initialization.

## Recipe contract

`managed.Catalog` / `Recipe` and exported `InstallCatalog.schema.json` are authoritative. A recipe binds app ID, release/platform, downloads (HTTPS URL plus SHA-256), settings (key/label/type/default/secret), generated literal configuration inputs and a typed Native/Docker application. Published `(app, release, platform)` content is immutable even if temporarily withdrawn. Jobs persist the selected recipe digest. HTTPS provides server trust; no independent private CA or per-owner client certificates are provisioned. Use a release source trusted to distribute executable code.

Settings are single-line bounded values; optional `generate` creates private URL-safe credentials. Types include text, port, name and URL-safe password. Templates use `${root}` (this app's namespace), `${package}` (protected Job cache), `${release}` and declared setting names. Only generated settings can use the `generated` digest marker. A numeric port may use `{"setting_int":"PORT"}`. Native program paths must be `${root}/releases/${release}`. Write/copy destinations remain inside the app namespace; traversal/symlinks are refused. Root/data/config namespaces and installer history remain separate. Docker uses the fixed local daemon, non-root runtime, fixed mounts/ports and no privilege/capabilities/anonymous volumes.

`dependencies` are real provider/version ranges, not a requirement to install every app. An installed consumer can also block an incompatible provider update. Generation Controller is a matched embedded component of Generation. External ComfyUI/GPT-OSS/Irodori-TTS, model files and PostgreSQL installation are outside these recipes. GNM initially has an empty runtime-profile directory; its own runtime setup happens afterward.

`compatible_from` explicitly authorizes the simple update path without schema transformation. New data/schema migrations require app-owned integration; there is no guessed reverse migration or DB rollback. Existing mutable settings/mounts are reused rather than overwritten by the new recipe.

## Administrator-only profile path

The protected `install-profile --profile /absolute/private.json --check` / `install-profile --profile ...` command from PR #11 remains available for controlled direct profile tests. Exact `install.Configuration` schema, package digests and hostname/platform checks apply. Installation records are per application, so a later app is permitted. It never imports an existing deployment. It is not the ordinary Web setup path and does not silently register its separate test profile as a simple managed app.
