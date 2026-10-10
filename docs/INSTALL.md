# Release recipes and direct installation

The normal operator flow is [running](RUNNING.md): bootstrap, register catalogs, select an app, first setup, verify, then update through the same records. It needs no pre-running app, application Owner, DB backup, system backup or client certificates.

## Repository-owned releases

Each application repository builds and publishes its own Docker archive or Native offline wheelhouse and catalog. Updater does not clone/build the applications or copy their payloads into a shared distribution. One app/platform is sufficient; releases can be published independently.

The recipe helper can generate a catalog from application-owned candidate metadata:

```bash
python scripts/build_install_catalog.py --candidate /absolute/app/candidate.json https://github.com/example/app/releases/download/v1.0.0 --output /absolute/app/catalog.json
```

`candidate.json` records application ID, release, source revision, platform, file digests, optional compatible predecessors and Docker image ID. It is produced and checked by the application's release process. Catalog generation preserves those direct URLs without copying assets. For SQL/subdirectory assets, the maintainer supplies release asset URLs in `Recipe.downloads`; the logical package key can retain a directory even though a GitHub asset has a flat filename.

A repository can also supply `Catalog`/`Recipe` JSON directly, including Native applications composed with another package. `entrypoint` and `distribution` identify the Native package launcher and version to verify; defaults retain the existing GNM contract. No private deployment identity is included in public defaults. Internal catalogs may use a separately reachable HTTPS source; private GitHub authentication is not implemented by Updater.

The catalog contains exact URLs, hashes, settings and compatibility. Register multiple catalog URLs in Web/CLI/MCP; a shared catalog may reference different repositories. Ordinary release downloads still require bounded HTTPS and digest verification.

The corrected managed downloader in current source accepts at most five HTTPS
redirects for catalogs, app payloads and supervisor self-update bundles. Redirects
stay on the initial origin, with one explicit exception: a
`https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>` or
`.../releases/latest/download/<asset>` URL can reach
`https://release-assets.githubusercontent.com` (default HTTPS port only).
The exception uses exact hosts, not wildcards or host suffix matching. HTTP,
credentials in URLs, fragments, traversal and unrelated hosts are rejected before
the next request. Ambient Authorization/Proxy-Authorization headers, Cookies and
client authentication are excluded from public release requests. Every response
is closed; final byte budgets, SHA-256/index validation and immutable recipe
bindings remain enforced. The separate signed/coordinator/registry fetcher keeps
its strict no-redirect contract.

Publish each repository's assets/catalog at its own selected HTTPS location
and verify its downloads/checksums. GitHub Release download
URLs are supported by distribution 1.0.3; the earlier 1.0.1 package rejects
redirects. Existing installations need administrator
maintenance of the pinned supervisor as well as Web/manager; updating only those
two services leaves the old self-update downloader in place. No live maintenance
is performed by this source change. An Actions artifact is a build output, not
a release source. The example domain above is not a published catalog. Do not
change URLs or content for a published app/release/platform identity; the manager
binds the entire recipe immutably. Hosting/proxy provisioning remains separate.

Generated recipes describe actual app environment fields, new database initialization and program/data layout. Operator choices and generated credentials are private local settings; they are not embedded in public candidates. Agent applies its own schema/migration SQL to a newly-created dedicated DB; Studio runs its own image Alembic. Neither operation touches existing DBs or creates backups. Users supply the PostgreSQL admin connection and a host reachable from both manager and app; unknown/occupied DB/role names stop before initialization.

## Recipe contract

`managed.Catalog` / `Recipe` and exported `InstallCatalog.schema.json` are authoritative. A recipe binds app ID, release/platform, downloads (HTTPS URL plus SHA-256), settings (key/label/type/default/secret), generated literal configuration inputs and a typed Native/Docker application. Published `(app, release, platform)` content is immutable even if temporarily withdrawn. Jobs persist the selected recipe digest. HTTPS provides server trust; no independent private CA or per-owner client certificates are provisioned. Use a release source trusted to distribute executable code.

Settings are single-line bounded values; optional `generate` creates private URL-safe credentials. Types include text, port, name and URL-safe password. Templates use `${root}` (this app's namespace), `${package}` (protected Job cache), `${release}` and declared setting names. Only generated settings can use the `generated` digest marker. A numeric port may use `{"setting_int":"PORT"}`. Native program paths must be `${root}/releases/${release}`. Write/copy destinations remain inside the app namespace; traversal/symlinks are refused. Root/data/config namespaces and installer history remain separate. Docker uses the fixed local daemon, non-root runtime, fixed mounts/ports and no privilege/capabilities/anonymous volumes.

`dependencies` are real provider/version ranges, not a requirement to install every app. An installed consumer can also block an incompatible provider update. Generation Controller is a matched embedded component of Generation. External ComfyUI/GPT-OSS/Irodori-TTS, model files and PostgreSQL installation are outside these recipes. GNM initially has an empty runtime-profile directory; its own runtime setup happens afterward.

`compatible_from` explicitly authorizes the simple update path without schema transformation. New data/schema migrations require app-owned integration; there is no guessed reverse migration or DB rollback. Existing mutable settings/mounts are reused rather than overwritten by the new recipe.

## Administrator-only profile path

The protected `install-profile --profile /absolute/private.json --check` / `install-profile --profile ...` command from PR #11 remains available for controlled direct profile tests. Exact `install.Configuration` schema, package digests and hostname/platform checks apply. Installation records are per application, so a later app is permitted. It never imports an existing deployment. It is not the ordinary Web setup path and does not silently register its separate test profile as a simple managed app.
