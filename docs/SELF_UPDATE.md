# Self-update, MCP continuity and logging review

Current work adds Updater Web/manager self-update and persistent MCP credentials.
External software/access setup, failure recovery, application DB upgrades and
general logging enhancements are outside this change. Source/CI evidence is not
release publication or installation on a real host.

## Self-update contract

New bootstrap starts three services: unprivileged Web, local root manager and
independent root supervisor. The supervisor stays in its original installation
so stopping/replacing the first two does not stop the update controller. Never
delete that installation. Updating the pinned supervisor itself remains explicit
bootstrap maintenance; this is not a claim to replace every privileged component.

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
HTTP 200 or an active unit. Settings, principals, keys and history stay in place.

Current and immediately previous Updater records are retained; staged self
bundles and the original supervisor installation are not automatically deleted.
Application current-plus-one cleanup remains independent. Failed/interrupted
self Jobs retain their candidate, completed steps and last intent, stop at
`recovery_required`, block subsequent local work, and are not replayed or rolled
back automatically. Detailed exception output is not included in public Jobs.

## Continuing MCP operation

The existing 24-hour tokens remain available. A password-authenticated Web
operator can issue/rotate/revoke a separate persistent key, granting read-only or
read/execute access to that operator's targets. It has no operator/credential
issuance authority. Only its hash is persisted; the secret is returned once.
Owner disablement or any owner authority revision invalidates keys. Rotation
immediately invalidates the previous secret; the client must receive the new one.

The Streamable HTTP server is stateless. Self-update causes a temporary outage,
after which clients can reconnect to the same URL with the same valid key and
read the same durable Job. A lost update response is reconciled with the same
request key. Client reconnection policy, HTTPS proxy/tunnel availability and
external client credential storage are deployment responsibilities. There is no
promise that an in-flight HTTP connection survives process replacement.

Human intervention: first bootstrap/Web account and initial client key setup;
later key rotation/revocation or changed access; selection/authorization of an
update and investigation if a Job stops. Compatible update execution and status
inspection are callable through MCP. No daily token reissue is needed when using
a persistent key. Scheduled automatic checking/updating is not added.

## Existing ordinary application logs: investigation only

| Evidence | Recorded | AI through Updater MCP |
| --- | --- | --- |
| Managed Job | ID, app/release/action, created time, latest phase/step, error code, retained candidate and cleanup state | `updater_managed_job_get`; recent 100 via `updater_managed_history` |
| Previous completed app steps | Ordinary `Manager.persist` overwrites latest Job; event records are generic type/ID/outcome/hash links, without per-step details/timestamps | No complete app step timeline |
| Local effect journal | `journal.sqlite` and chained `recovery.jsonl`; separate installer substeps persist locally | No MCP event-log/file-reading API |
| Command diagnosis | Installer captures stdout for internal checks; stderr is discarded and outputs are not stored as diagnostic logs | No stdout/stderr, exit context or detailed failure explanation |
| New self-update Job | Ordered step intents/verified outcomes/times, candidate path, result/error code and both runtime versions | Existing managed Job/history tools include these fields |

The current app logs identify where work stopped and which old/candidate state
was retained. They are insufficient to reliably reconstruct every completed
action or diagnose a command failure using Updater MCP alone. Inspecting local
logs needs an independently authorized host tool. This investigation adds no
ordinary app log enhancement or general MCP log-reading feature. A subsequent
proposal would require user approval and secret-safe, bounded structured logs.

## Validation boundary

Tests exercise real indexed archive staging, protected journals, candidate
read-only probes of both SQLite stores, Web/session/MCP authentication, key
revocation/rotation/owner changes and supervised Job failure/interruption. Only
systemd and running service identity commands are controlled in the self Job
tests. Native-bundle CI separately imports the actual packaged dependencies and
checks its runtime identity on amd64/arm64. This does not certify real host
service replacement, external clients, tunnels or application domain behavior.
