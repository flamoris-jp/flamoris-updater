# Simple flow implementation review

The goal is installation for new users and later settings-preserving updates,
not reproduction/preservation of a particular deployment. No real host, app/data,
release publication or external runtime was modified by this source work.

## Counterexamples corrected

- The original planner/Owner/runner required snapshots and isolated DB restore
  before migration/activation. Those operations/fields and actual DB/tree backup
  implementations are removed. Writer fences/domain migration remain app-owned;
  incompatible old executables cannot trigger data restore.
- Coordinator/helper schemas required one app before Web could start. Empty
  inventories are accepted, and bootstrap Web uses a source-independent journal
  and first setup with no app/Owner dependency.
- PR #11 recorded an entire host as installed once. Records are now per app;
  normal recipe install/update uses one shared app registry and durable Jobs.
  Parent traversal in copied/mounted/native paths is rejected before effects.
- A health/running requirement before first setup blocked legitimate empty
  installs. Normal install provisions stopped services and records awaiting setup;
  setup/start and health verification are explicit later operations.
- A new provider could break an installed consumer. Outgoing real dependencies
  and incoming consumer compatibility both constrain admission; optional app
  connections do not create an install group.
- Successful updates could accumulate executables/caches, or cleanup could race
  a failed update. Retention is current plus one previous, only after verification;
  exact recorded executable paths/containers/images and cache IDs are checked.
  Active/unknown Jobs block manual cleanup; config/data/runtime namespaces never
  enter the delete list. Docker never forces image removal used elsewhere.
- A crash between steps could appear queued again. Intermediate state is running/
  intent and restart marks it recovery-required without effect replay.
- A 100-row history page could hide pending work/cleanup blockers. Worker and
  blocker queries use all active records; display history is bounded separately.
- Withdrawn then reintroduced release content could evade immutability checks.
  Persistent per-release digest records outlive catalog withdrawal.
- A root public Web or persistent stale helper socket was unnecessary. Web runs
  as its own service user, OS peer checks guard the root helper, and systemd owns
  the temporary socket directory. Setup code/credential values are not subprocess
  arguments or ordinary job/history responses.

## Evidence and limits

Tests exercise real settings/files/SQLite/Auth/Web/MCP/CLI, actual offline native
virtual environments/wheel install and metadata checks. Docker/systemd effects
are controlled adapters in the shared flow tests. Dedicated CI also exercises
actual Generation Docker installation and fresh PostgreSQL role/DB creation.
Local named Unix listeners and actual PostgreSQL/Docker are environment-limited;
socket-pair OS credentials/framing checks run locally. Production API/version/
domain behavior, every application's first setup/external connection and real-host
acceptance are separate from those fixtures.

Candidates/catalog recipes are generated for all six deployment units. They are
not automatically published. Existing app SDK pins remain for their optional
advanced Owner integration; the simple path does not activate/import that state.
The simple update path requires explicit schema/settings compatibility; new
schema handlers remain application integration work. Updater/root-helper self
replacement remains reviewed maintenance, not automatic application cleanup.
