# Draft 1 design review

Date: 2026-10-08. **Documentation review, not runtime tests or deployment acceptance.**

## Scope

Reviewed current Updater main and the pinned source references in [adoption](ADOPTION.md). Produced only Markdown specifications and updated entry/status guidance. No schema validator, code/package, workflow, script, DB DDL, host unit, owning-repository change or live infrastructure operation is included.

## Findings resolved in the draft

| Finding | Resolution |
| --- | --- |
| Repository/version could be mistaken for restartable deployment | Separate application/deployment/component identities; preserve agreed tag/package distinctions |
| Independent config/DB routes could create an unsupported pair | Plan over guarded schema vectors with unambiguous supported routes |
| Signature alone could leave release replay/withdrawal unresolved | Signed expiring monotonic catalog, immutable-release conflict and revocation checks |
| Fresh catalog sequence could unnecessarily alter authorization | Plan binds minimum sequence/exact digests; freshness adds confirming evidence only |
| Plan creation advertised as purely read-only despite persistent metadata | Distinguish no target mutation from MCP readOnly annotation |
| Backup archive success could be mistaken for verified recovery | Exact Job-bound consistent snapshot and isolated restoration/domain validation |
| Lost response/timeout could cause migration replay | Durable request/operation identities, persistent blockers and owner reconciliation |
| DB grouping could ignore shared/external writers | Registered consistency domains; unknown writers and missing maintenance fence block updates |
| Existing Controller health/Manager lock could be treated as a maintenance API | Record missing integration contracts explicitly as owning-app implementation gaps |
| Group gate reopen might fail after some writes are accepted | Reconcile accepted work; no automatic restore behind possible new writes |
| Recovery verification could become an implicit repair/authorization bypass | Exact verification grant; evidence only, protected controller finalizes release |
| Self-update rollback could restore stale journals and lose replay protection | Stable recovery controller/journal v1; pointer recovery only, no blind journal restore |
| Initial install could erase unmarked existing resources | Explicit absence proof/initializer contract; preserve partial/unknown new data |
| Generic dependency ordering could ignore cycles | Reject cycles without an explicit validated gated group profile |
| Core reuse could imply .NET imports or a separate repository | Python transport-neutral packages in the same repo; no unnecessary bridge/split |
| Native install might build on a managed host | CI bundle or declared verified interpreter; missing dependencies block preparation |

## Documentation verification

- Checked 18 Markdown files and 74 relative links/anchors.
- Parsed all 4 fenced JSON examples as illustrative fixtures; placeholder digests are explicitly not valid production releases.
- Draft/unimplemented wording, management-entry policy and cross-document status checked.
- Changes are Markdown only; existing license, Issue forms and other base files preserved.
- No private hostnames/topology, secrets or live-status claims added.

## Dedicated Web correction (2026-10-08)

At the user's instruction, superseded the proposed Studio update-management projection with a dedicated Updater Web adapter. Updated active identity/architecture/API/adoption/roadmap/authorization guidance and added WEB_UI.md. Studio source inventory and application-adoption requirements remain valid; no cross-repository integration or implementation was added.

Web owns independent authentication/session/CSRF, consumes the same coordinator and preserves CLI/controller-only self-update/restoration in v1. Reviewed shared Job identity, browser response-loss behavior, Studio downtime and Web unavailability during coordinator self-update. Additional Web cases are future acceptance criteria, not executed browser tests. Verified the revised documentation set: 19 Markdown files, 85 relative links and 4 illustrative JSON examples; no active Studio-integration plan remains.

## Limits and remaining evidence

The architecture/contract draft is complete for this task. Application-specific handlers, exact schema/resource mappings, live inventory, DB writer/role scopes, trusted key provisioning, actual package compatibility and runtime/fault/live acceptance remain later work.

No future acceptance case is reported as executed. The user explicitly holds implementation; [roadmap](ROADMAP.md) and [progress](../PROGRESS.md) preserve that hold.

## Later review loop

The [review/correction loop](REVIEW_LOOP_2026-10-08.md) records a subsequent two-round review of the dedicated-Web design and final consistency corrections. The verification totals above remain the historical checks for their respective earlier changes.
