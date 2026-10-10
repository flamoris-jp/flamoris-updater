# Self-update, MCP continuity and logging review

Updater supports Web/manager self-update and AI-readable effect/layout evidence.
Updater credentials have been removed. External software/access setup,
automatic failure recovery and application DB upgrades are outside this change. Source/CI evidence is not
release publication or installation on a real host.

## Version 1.0.4 catalog

The publication workflow generates `catalog.json` from both verified Native bundle
summaries. It points directly to this repository's immutable v1.0.4 Release assets,
sets `compatible_from` to `["1.0.3"]`, and includes the catalog in `SHA256SUMS`.
Register the Release asset URL in the existing 1.0.3 screen before selecting
1.0.4. Preserve the original supervisor installation and all control records;
do not run initial bootstrap over an existing installation.

Catalog URL after successful publication:
`https://github.com/flamoris-jp/flamoris-updater/releases/download/v1.0.4/catalog.json`.
It contains no application payloads or application recipes. Register each
application repository's own catalog separately after publication.

## Self-update contract

New bootstrap starts three services: unprivileged Web, local root manager and
independent root supervisor. The supervisor stays in its original installation
so stopping/replacing the first two does not stop the update controller. Never
delete that installation. Updating the pinned supervisor itself remains explicit
bootstrap maintenance; this is not a claim to replace every privileged component.

Distribution 1.0.3 applies the checked public-release redirect policy described in
[installation](INSTALL.md) to supervisor bundle downloads as well as manager
catalog/app downloads. The published 1.0.1 supervisor does not contain that
correction. Replacing Web/manager alone cannot enable GitHub Release downloads
for it; install a corrected distribution through explicit administrator bootstrap
maintenance with current Job/journal/binding inspection. This source work does
not modify a live pinned unit or discard the original installation.

The catalog's `updater_releases` bind release, platform, explicit compatible
predecessors, HTTPS Native archive digest/index/budget and supervisor protocol 1.
Maintainers can include a bundle with:

```bash
python scripts/build_install_catalog.py --updater-bundle dist/native/bundle-digests.json https://releases.example.invalid/updater/1.1.0 --compatible-from 1.0.0 --output dist/catalog.json
```

The recipe can coexist with repeated `--candidate` application recipes. A
withdrawn release cannot be republished with different contents. API callers
choose an available version and request key; they cannot choose paths/commands.

Only one local Job may be active. The supervisor records stage → stop →
control-check → switch → start → verify intents/outcomes with timestamps.
Staging verifies archive/index/files, release metadata, imports and runtime
identity. After stopping Web/manager, both existing journal stores must pass the
candidate's read-only v1 schema/content probe. No data migration occurs. Drifted
bootstrap configuration or managed units are rejected rather than overwritten.
Final checks require the actual Web and manager versions/runtime paths, not just
HTTP 200 or an active unit. Settings and history stay in place. Historical account records may remain in existing journals but are no longer used by the endpoint.

Current and immediately previous Updater records are retained; staged self
bundles and the original supervisor installation are not automatically deleted.
Application current-plus-one cleanup remains independent. Failed/interrupted
self Jobs retain their candidate, completed steps and last intent, stop at
`recovery_required`, block subsequent local work, and are not replayed or rolled
back automatically. Detailed exception output is not included in public Jobs.

## Continuing MCP operation

Streamable HTTP needs no Updater credential. Self-update causes a temporary outage; clients reconnect at the same URL and read the same durable Job. A lost response is reconciled with the same request key. Client reconnection and external proxy/tunnel access remain deployment responsibilities. Scheduled checking/updating is not added.

## Diagnostic evidence and manual recovery

Ordinary app install/update, setup verification, cleanup and self-update now record
structured intent/completion/failure timelines. Read-only scoped MCP tools
`updater_managed_log_get` and `updater_managed_layout_get` expose those records and
recorded current/candidate/previous placement. Command failures include fixed
classification and exit/errno context without raw output, credentials or SQL.
This supersedes the earlier investigation finding that latest Job state alone
was insufficient. Earlier Jobs do not receive invented retrospective logs.

If Updater Web/manager itself is unavailable, its MCP endpoint is unavailable.
Manual recovery through an independent administrator channel is required;
Server Manager can support AI investigation only if independently available.
See [AI-readable evidence and manual recovery](DIAGNOSTICS.md) for record fields,
limits, offline private exports, uncertainty and the human investigation procedure.

## Validation boundary

Tests exercise real indexed archive staging, protected journals, candidate
read-only probes of both SQLite stores, credential-free Web/CLI/MCP continuity and supervised Job failure/interruption. Only
systemd and running service identity commands are controlled in the self Job
tests. Native-bundle CI separately imports the actual packaged dependencies and
checks its runtime identity on amd64/arm64. This does not certify real host
service replacement, external clients, tunnels or application domain behavior.
