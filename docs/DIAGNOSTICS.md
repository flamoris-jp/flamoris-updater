# AI-readable deployment evidence and manual recovery

Implemented source: bootstrap-managed app install/update, initial setup checks,
executable cleanup and supervised Updater self-update record structured evidence.
This supports **AI preparing a recovery procedure after failure** and **AI
documenting the recorded installation layout**. It does not execute recovery,
restore data, change DB schemas, or replace Server Manager's live observations.
Source/tests/CI do not mean publication or real-host acceptance.

## Reading evidence through MCP

The tools use the same credential-free Web/CLI/MCP endpoint.
The root helper verifies that a supplied Job belongs to that application.

| Tool | Request | Evidence |
| --- | --- | --- |
| `updater_managed_log_get` | `application_id`, `job_id`, optional `after` (sequence, default 0) and `limit` (1–50, default 25) | Job plus ordered effect records, pagination and recorded/live flags |
| `updater_managed_layout_get` | `application_id`, optional `job_id` | Current registration, selected/latest candidate and its previous layout, selected Job and retained executable pointers |

Use `flamoris-updater` as the application ID for self-update. For ordinary apps,
use the catalog application ID. These are typed records, not arbitrary log-file
or shell access. Historical Jobs created before this feature have no reconstructed
timeline: `recorded=false`. Pagination `complete` means the available page stream
is exhausted, not that the Job succeeded. Continue with `next_after` while
`has_more=true`; save `last_sequence` for later polling as the Job progresses.

Each effect includes sequence, millisecond timestamp, nested step, operation and
`intent` / `completed` / `failed` outcome. Job metadata records source/target
release, action, host, platform and recipe digest. Downloads record member,
destination and digest; configuration copies record destination/ownership/mode;
DB initialization records database/role names and initialization file/digest.
Runtime switch, health verification, cleanup and unit replacements are distinct.
Failure records include bounded error code, fixed kind, exit code, OS errno,
SQLSTATE or fixed diagnostic hint when available, and elapsed time. Hints are
classification aids, not proof of cause. Raw exceptions, argv, SQL, stdout/stderr,
settings values, passwords and tokens are not exported. Private settings are also
redacted from descriptive paths. There is no generic subprocess-output log.

The layout lists config/data directories with ownership/mode, config destinations,
native release directory/Python/unit names and paths, or Docker image/container,
mounts/network/ports, plus DB name and roles when present. Updater layout includes
Web/manager state directories, config, local socket, application storage, endpoint,
three units and pinned supervisor executable. Config contents, environment values
and database connection credentials are excluded. External DB/network details
not represented by these bindings require separately authorized observations.

`current` is the last registered installation. A failed switch may already have
changed the actual service while that registration still describes its predecessor.
`candidate`, `previous_layout`, Job phase and intent records expose this distinction;
all layout results say `live_state=false`. Prior executable pointers are not data
backups or a safe rollback plan. The response shows at most 20 older pointers and
their total count. A candidate may be absent when failure occurred before compilation.

AI workflow:

1. Read Job/history, every available log page, and current/candidate/previous layout.
2. Identify verified completions, failed effects and intents without confirmed outcome.
   A failed command may have partially changed state. Never infer that nothing happened.
3. Obtain current service/container/file/DB observations through Server Manager or
   another independently authorized administrator channel. Do not duplicate that
   infrastructure API in Updater.
4. Prepare a recovery procedure with evidence, uncertainty, required observations
   and proposed human actions. For an installation document, separate recorded
   placement from independently confirmed current placement; omit secrets.

## Durable storage and limits

The manager's existing `journal.sqlite` records table is authoritative; no schema
migration is introduced. After each append, an atomic private mirror is written
to `<helper_state_directory>/diagnostics/<job_id>.jsonl`. The corresponding
`<job_id>.layout.json` preserves the selected candidate and previous layout for
offline inspection. The directory is mode 0700 and exports 0600. SQLite retains
records even if an abrupt failure leaves the mirror shorter. Preserve both stores
and exports; ordinary executable/cache cleanup does not remove them.

Intent must be committed and exported before its effect starts. Failure to write
evidence stops the next effect; it is not permission to retry an earlier effect.
Limits are 4,096 entries per Job, 8 KiB per entry and 256 KiB per layout snapshot.
Exhaustion fails closed and retains existing evidence. Cleanup/setup actions use
their installation's Job timeline. Retention is explicit: there is no automatic
diagnostic/history pruning. Plan storage capacity as part of host operation.

## When Updater itself is stopped

**Updater MCP cannot inspect logs or perform actions when Web or the local
manager is unavailable. Recovery then requires an independent administrator
channel and human intervention.** If Server Manager is independently available,
AI can use that authorized channel to inspect evidence and draft a procedure;
otherwise an administrator must use the host's normal console/SSH access. No
automatic recovery API or emergency credentials are added.

The supervisor normally survives intentional Web/manager replacement, but it
cannot guarantee recovery from supervisor failure, host loss, broken configuration
or an incompatible executable. Its original runtime must remain installed.

Manual investigation procedure:

1. Stop the three Updater services before editing or replacing executables, units,
   configuration or control stores: `flamoris-updater-supervisor.service`,
   `flamoris-updater-manager.service`, `flamoris-updater.service`. Record their
   current unit bindings and preserve the journals/exports. Use actual unit paths
   and `--config` bindings; bootstrap normally stores `setup.json` beside its
   `web` and `helper` state directories. Do not assume a deployment path.
2. Inspect the Job JSONL/layout mirrors and the authoritative helper journal
   read-only. In SQLite, Jobs are `records` rows with `kind='managed_job'`, and
   effect/layout rows use `managed_log` / `managed_layout`. Inspect service startup
   logs through the independent administrator channel where necessary. These
   external logs may contain sensitive details and must not be copied wholesale
   into AI documentation.
3. Check for queued `accepted` Jobs as well as `intent`, `running` and
   `recovery_required` Jobs. Starting the manager or supervisor can execute queued
   accepted Jobs. Interrupted running/intended Jobs become `recovery_required`
   without replay; missing completion evidence still requires live verification.
4. Compare actual Web/manager unit executables, candidate/previous runtimes,
   bootstrap-pinned supervisor, config and control-store compatibility. Prepare
   a procedure for the observed stopping point; do not blindly point both units
   back, delete candidates, clear a blocker or restore an old journal.
5. Have an administrator apply the reviewed procedure and start only services
   whose bindings and queued work have been checked. Confirm service identity,
   endpoint/key access, Job and retained evidence afterward. Restart alone does
   not clear `recovery_required`; resolving that blocker remains manual work.

Keep the existing authentication and history stores. Replacing them can invalidate
MCP keys or erase the evidence needed to determine which effects happened. Service
restart and self-update compatibility checks do not constitute data restoration.
