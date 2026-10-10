# Release recipes and direct installation

The normal operator flow is [running](RUNNING.md): bootstrap, Web setup, select an app, first setup, verify, then update through the same records. It needs no pre-running app, application Owner, DB backup, system backup or client certificates.

## Maintainer-owned inputs

`scripts/build_initial_candidate.py` builds immutable Docker archives or GNM offline wheelhouses from exact reviewed source commits. It validates package/image/component versions and writes `candidate.json` with platform, image ID, file digests and source revision. Initial defaults are AI 1.0.0 / GNM 1.2.0. `--revision`, `--version` and repeated `--compatible-from` support later explicitly compatible releases. These arguments are maintainer/CI inputs; caller APIs do not accept commands/source revisions.

```bash
python scripts/build_initial_candidate.py --application flamoris-generation-mcp --platform linux/amd64 --output dist/generation
python scripts/build_install_catalog.py --candidate dist/generation/candidate.json https://releases.example.invalid/generation --output dist/catalog.json
```

Distribute that catalog and its candidate files at the selected direct HTTPS locations (no credential/client certificate or implicit registry login). The source example is illustrative, not an available release. Controlled CI uses disposable candidates before publication.

### Complete initial distribution

The manual **Initial installation candidates** workflow takes `base_url`, the
chosen immutable HTTPS directory. It builds all six applications on
amd64/arm64, validates the complete matrix and uploads an
`initial-install-distribution` artifact containing `catalog.json`, flat uniquely
named payload files, `application-distribution.json` and `SHA256SUMS`. It has
read-only repository permissions and performs no publication or host installation.
Download artifacts without merging their candidate directories when assembling
outside the workflow:

```bash
python scripts/package_install_catalog.py --candidates dist/candidates --base-url https://releases.example.invalid/initial-apps --output dist/distribution
```

The packager requires the reviewed source commits and initial release identities
from `build_initial_candidate.py` / `install.VERSIONS`. It refuses missing or
duplicate app/platform entries, source/published-state mismatches, unlisted fields/files,
symlinks, changed digests, oversized payloads and existing/overlapping output.
Public asset names are distinct; logical package keys remain unchanged, including
SQL paths and wheel filenames. The generated catalog is revalidated against the
installed schema and one-MiB catalog budget. Assembly metadata records
`published=false`; it describes the build checkpoint, not live hosting acceptance.
Future releases need a separately reviewed matrix rather than bypassing these
initial identity checks.

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

Publish the assembled assets and catalog together at the selected HTTPS location
and verify every download and checksum before Web setup. GitHub Release download
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
