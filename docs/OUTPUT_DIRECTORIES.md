# Operator media directories

Updater 1.0.11 adds `updater_outputs_configure` through the same Web, MCP and CLI
Job path. It configures the YuE2 publication directory for an installed
Generation image with Controller 1.0.1 or newer. Other providers retain their
existing configuration; this is not a general mount or environment editor.

The Generation card shows **YuE2の出力先** after initial setup completes. Supply an
existing absolute host directory. The runtime UID/GID 10001 must be able to read,
write and traverse it, including its parents. Updater checks permissions with
that identity, including ACLs. It does not create directories, change ownership
or permissions, move existing files, or delete media. Symlinks, system paths,
managed app/state overlap and private-mount overlap are refused.

Finish generation before changing the directory and do not submit another job
until the configuration Job finishes. The manager checks authenticated
Controller idle status immediately before stopping Generation. This check is
not a fence against another client submitting work concurrently. No GPU runtime
switch or generation is performed by the configuration operation.

Web saves the choice via this same typed request:

```json
{
  "application_id": "flamoris-generation-mcp",
  "request_key": "operator-output-choice-1",
  "directories": {"yue2": "/srv/media/music"}
}
```

CLI uses `flamoris-updater call --url <updater-url> --tool updater_outputs_configure
--arguments <json-file-or-stdin>`; consult `call --help` for the installed syntax.
The directories/key are not secrets. Reuse the same request key after a lost
response; different arguments under that key are refused. Poll
`updater_managed_job_get` with the returned `job_id`. A new key represents a new
operator choice, not a recovery retry. An empty `yue2` value disables publication
and removes the dedicated mount without deleting any output.

The source of truth is the installed profile's `output_directories`. Generation
receives a writable bind at `/data/music-output` and an explicit Docker
environment override `FLAMORIS_YUE2_OUTPUT_ROOT=/data/music-output`. The protected
`runtime.env` bytes are preserved. An empty choice overrides that variable with
an empty value. Recorded layout exposes media directories/mounts separately
from private mounts and configuration.

Configuration is a durable Job at the same release: the installed package,
image and settings stay the same; the previous container is retained until a
verified replacement is running. Configuration Job identity is separate from
the current executable package Job, so previous deletion cannot remove the
current package. Normal subsequent compatible releases reuse the operator
choice; catalogs cannot supply media directories or silently overwrite it.
Ordinary mount/security drift remains rejected.

Failure/interruption records `recovery_required`, retains the old container and
does not replay the operation automatically. Do not resubmit with another key;
inspect recorded layout/logs and actual containers with Server Manager. There
is no promise of automatic rollback. Completed human media copies are managed
by the operator, while private Job archives and reproducibility authority remain
in Generation's original outputs area. See the owning Controller storage guide
for publication naming and deletion behavior.

Public defaults contain no private host path. The example above is illustrative;
deployment-specific paths and acceptance records belong in private operations
documentation.
