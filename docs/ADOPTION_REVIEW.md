# Application adoption review — 2026-10-08

The source review/fix loop is complete and all eight repositories have successful
CI evidence. The operator made flamoris-updater public, resolving the anonymous
SDK download 404. A subsequent Agent container failure was corrected and both
Agent jobs passed. All eight PRs were merged after explicit user authorization;
source completion does not publish releases or certify real-host adoption.

## Evidence

| Repository | PR | Local tests | Package build | CI evidence |
| --- | --- | --- | --- | --- |
| Updater | #6 | 132 passed, 2 skipped | wheel/sdist/SDK | Run 37765729268: all 4 jobs succeeded, including real isolated restore and both architectures |
| Agent | #45 | 175 passed, 34 skipped | wheel from sdist | [37768251469](https://github.com/flamoris-jp/flamoris-ai-agent/actions/runs/37768251469): test/container succeeded; 209 tests passed against disposable PostgreSQL 16 |
| Studio | #69 | 232 passed, 147 skipped | wheel from sdist | [37766780241](https://github.com/flamoris-jp/flamoris-studio/actions/runs/37766780241): server/web/container succeeded; 379 tests passed against disposable PostgreSQL 17 |
| Intelligence | #14 | 104 passed | wheel from sdist | [37766158343](https://github.com/flamoris-jp/flamoris-intelligence-mcp/actions/runs/37766158343): Python 3.11/3.12 and container succeeded; 104 tests passed |
| Generation MCP | #74 | 196 passed | wheel from sdist | [37766397836](https://github.com/flamoris-jp/flamoris-generation-mcp/actions/runs/37766397836): 196 tests, installed wheel and container succeeded |
| Controller | #9 | 295 passed | wheel from sdist | [37765917211](https://github.com/flamoris-jp/flamoris-generation-controller/actions/runs/37765917211): Python 3.11/3.12 succeeded; 295 tests and MCP/HTTP-free installed import passed |
| Hub | #41 | 160 passed | wheel from sdist | [37766172019](https://github.com/flamoris-jp/flamoris-mcp-hub/actions/runs/37766172019): 160 tests and lint/format passed |
| GPU Node Manager | #13 | 499 passed, 7 skipped | wheel from sdist | [37766184979](https://github.com/flamoris-jp/flamoris-gpu-node-manager/actions/runs/37766184979): 506 tests, mypy, lint/format and wheel succeeded |

The local application skips were exercised in CI using disposable PostgreSQL or
compatible procfs. The real Updater PostgreSQL 14
job actually dumps and restores a disposable database in a network/PID-isolated
namespace, verifies contents/schema/authorization and rejects a modified dump.
GPU source mypy (35 files) and full Ruff check/format passed. Six applications
passed full Ruff; Studio's new Owner/test files passed targeted Ruff, while its
existing files retain their baseline formatting. All seven built distributions
were checked for their declared Owner entrypoint/module.

All applications pin SDK source d9f010a92ff6e8a1e7a3b7fad8817850bdfb72cd.
The Agent container correction is d7b7b26318c246c7a202f966438775d63fe6410c;
other app code revisions are recorded in their PRs. Subsequent progress-only
commits preserve those source/dependency identities. Successful isolated CI
fixtures do not certify private production databases, providers or overlays.

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
9. Build the separate Intelligence source wheel with --no-deps in Agent's Docker
   wheelhouse, then resolve runtime dependencies from the fixed snapshot once.
   Reject inconsistent installed dependencies with pip check. This removes the
   duplicate cryptography versions found by real container CI.

## Remaining boundaries

Source CI, installed dependency integration and CI container acceptance succeeded.
Source integration is complete; operational acceptance remains separate. No release
publication, signing/trust provisioning, production migration, host update or
enrollment occurred. Native candidates must retain the private deployment overlay
and matched dependencies. Provider-owned retained paths and mixed-ownership trees
need an explicitly supported protected profile; they cannot be silently omitted.
The entry path preserves already current schemas and requires reconciliation after
unknown outcomes; it does not claim automatic data rollback or atomic host groups.
