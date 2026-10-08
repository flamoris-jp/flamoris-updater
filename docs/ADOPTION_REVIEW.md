# Application adoption review — 2026-10-08

Source and local verification are prepared in eight draft PRs. The application
CI/review loop is **not complete**: anonymous installation of the pinned Core SDK
returns HTTP 404 because flamoris-updater is private. Repository visibility was
confirmed through GitHub metadata; no visibility, credentials or trust settings
have been changed. Private cross-repository read access or an explicit source
publication decision is required before final integration CI can run.

## Evidence

| Repository | PR | Local tests | Package build | CI evidence |
| --- | --- | --- | --- | --- |
| Updater | #6 | 132 passed, 2 skipped | wheel/sdist/SDK | Run 37765729268: all 4 jobs succeeded, including real isolated restore and both architectures |
| Agent | #45 | 175 passed, 34 skipped | wheel from sdist | Run 37766384049: SDK installation 404 |
| Studio | #69 | 232 passed, 147 skipped | wheel from sdist | Run 37766780241: web succeeded; server/container dependency blocked |
| Intelligence | #14 | 104 passed | wheel from sdist | Run 37766158343: SDK installation 404 |
| Generation MCP | #74 | 196 passed | wheel from sdist | Run 37766397836: SDK installation 404 |
| Controller | #9 | 295 passed | wheel from sdist | Run 37765917211: SDK installation 404 |
| Hub | #41 | 160 passed | wheel from sdist | Run 37766172019: SDK installation 404 |
| GPU Node Manager | #13 | 499 passed, 7 skipped | wheel from sdist | Run 37766184979: SDK installation 404 |

Skipped application tests require real disposable PostgreSQL or compatible procfs;
source-only success does not replace those checks. The real Updater PostgreSQL 14
job actually dumps and restores a disposable database in a network/PID-isolated
namespace, verifies contents/schema/authorization and rejects a modified dump.
GPU source mypy (35 files) and full Ruff check/format passed. Six applications
passed full Ruff; Studio's new Owner/test files passed targeted Ruff, while its
existing files retain their baseline formatting. All seven built distributions
were checked for their declared Owner entrypoint/module.

## Corrected review findings

1. Bind an Owner Job before the first fenced operation; preserve one claim/epoch
   and compare signed host activation with the actual target boot.
2. Preserve cancelled/unknown work across restart and refuse implicit replay.
   Retained Controller reservations, Agent/Studio history and failed GPU
   inspections are read without reset or constructing a second authority.
3. Compare PostgreSQL application-role memberships consistently on both sides;
   normalize timezone/date/interval/float representations. Real CI caught the
   parameterized SQL percent handling and built-in membership mismatch.
4. Recheck protected Helper/Entry configuration and environment bytes between
   effects. Bind Owner configuration/DSN revision to the claimed Job.
5. Fsync copied file and directory metadata before issuing a snapshot receipt.
   Refuse links, special files, expanded quotas and ownership normalization.
6. Verify activated container mounts, ports, user, network, limits and security
   policy before issuing host evidence.
7. Package the SDK independently of the MCP 1 Updater; preserve MCP 2 applications.
   Build wheel from sdist and match owning-library commits in all consumers.
8. Keep Studio update UI independent and avoid broad unrelated formatting changes.

## Remaining boundaries

All PRs remain draft. Final CI, installed dependency integration and container
acceptance must be completed after SDK access is resolved. No auto-merge, release
publication, signing/trust provisioning, production migration, host update or
enrollment occurred. Native candidates must retain the private deployment overlay
and matched dependencies. Provider-owned retained paths and mixed-ownership trees
need an explicitly supported protected profile; they cannot be silently omitted.
The entry path preserves already current schemas and requires reconciliation after
unknown outcomes; it does not claim automatic data rollback or atomic host groups.
