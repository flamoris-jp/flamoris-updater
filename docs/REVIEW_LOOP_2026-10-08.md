# Design review and correction loop

Date: 2026-10-08. Base: `3fbe5efe65c465b93d4e12c99712ee755c883bcc` (dedicated Web correction).

**Documentation-only self-review: two review/correction rounds followed by a final consistency pass.** No independent reviewer, executable implementation, runtime test or deployment acceptance is claimed.

## Scope and method

Read the current repository contracts, then trace counterexamples through plan admission, host effects, restart, recovery, self-update and the dedicated Web. Fix the affected specifications together, and re-read the resulting contracts for action, ownership and outcome consistency. Add the counterexamples to [future acceptance](ACCEPTANCE.md).

Preserved decisions: reusable Core and FLAMORIS wrapper in this repository; Updater-owned Web with independent authentication/session/CSRF; Studio as an application target; AI-side entry v1.0, GPU Node Manager v1.2 and Updater v1.0. Runtime implementation remains explicitly held.

Prior source inspection and historical verification are recorded separately in [draft 1 review](REVIEW_DRAFT_1.md). This loop does not re-inspect live hosts or declare owning applications compliant.

## Round 1: effect and persistence counterexamples

Priority describes the design impact of an uncorrected contract, not a demonstrated shipped vulnerability.

| ID / priority | Counterexample or gap | Correction / contract |
| --- | --- | --- |
| R1-01 High | One plan admitted with two request keys/grants creates two executions | One consumed plan/Job across every adapter; permanent consumption after terminal outcome; [execution](EXECUTION_RECOVERY.md#idempotency-and-reconnection) |
| R1-02 High | Reuse operation ID with altered payload or jump to activation without backup | Immutable operation binding and confirmed predecessor/group-barrier receipts; [execution](EXECUTION_RECOVERY.md#maintenance-continuity-restart-and-step-ordering) |
| R1-03 High | Old process lock vanishes and candidate/timer accepts work during migration | Durable resource-owner maintenance epoch across process replacement; controlled startup; [execution](EXECUTION_RECOVERY.md#maintenance-continuity-restart-and-step-ordering) |
| R1-04 High | Health succeeds before gates reopen or blockers are released | Explicit reopening/finalizing; local receipts before global acceptance transaction; [journal](EXECUTION_RECOVERY.md#proposed-journal-records) |
| R1-05 High | Two host-local aliases/locks allow concurrent mutation of one remote DB | Resolve one physical resource/owner and share its fencing contract, including standalone tools; [migration](MIGRATION_CONTRACT.md#shared-resources-immutable-operations-and-snapshot-isolation) |
| R1-06 Medium | Reconcile returns applied_verified but result envelope rejects it | Define allowed outcomes per operation; inspections cannot substitute for apply receipts; [envelope](MIGRATION_CONTRACT.md#requestresult-envelope) |
| R1-07 Medium | Re-fetching an unchanged catalog is treated as malicious replay | Same sequence plus same digest accepted; lower sequence or equal-sequence changed digest rejected; [release trust](RELEASE_MANIFEST.md) |
| R1-08 High | Verified staging changes before execution or loader searches writable paths | Protected sealed content, final identity check and trusted loader environment for activation/rollback; [release](RELEASE_MANIFEST.md#sealed-content-and-parser-budgets) |
| R1-09 Medium | Catalog/notes response grows without a bound or locator escapes its origin | Streaming/parser/response budgets, pagination and confined paths/origins; [release](RELEASE_MANIFEST.md#sealed-content-and-parser-budgets) |
| R1-10 High | Scratch candidate starts timers/replays jobs or uses production credentials | Owner-confined validation namespace/credentials with production effects blocked; unsupported drill blocks update; [migration](MIGRATION_CONTRACT.md#shared-resources-immutable-operations-and-snapshot-isolation) |
| R1-11 Medium | Fresh install/already valid deployment cannot provide a legacy transition receipt | Typed transition/installation/adoption evidence, all re-inspected; [enrollment](EXECUTION_RECOVERY.md#enrollment-evidence-and-control-state-compatibility) |
| R1-12 High | Pointer rollback reads old auth/trust state and revives consumed grants | Compatibility covers all control stores; retain current watermarks/revocations/tombstones; [self recovery](EXECUTION_RECOVERY.md#enrollment-evidence-and-control-state-compatibility) |

## Round 2: review of the corrected contracts

| ID / priority | Counterexample or gap | Correction / contract |
| --- | --- | --- |
| R2-01 High | Verification tool consumes a mutating recovery plan; verification action absent | Explicit verify_recovery action and action-based dispatch; no mutation/blocker release; [execution](EXECUTION_RECOVERY.md#action-dispatch-and-recovery-ownership), [MCP](MCP_API.md#action-separation-and-protected-role-checks) |
| R2-02 High | Failed parent's locks prevent recovery, or clearing them admits competing work | Read-only child observes stable blocked state; protected revision-checked ownership transfer to mutating child, with partial transfers blocked and original outcomes preserved; [ownership](EXECUTION_RECOVERY.md#action-dispatch-and-recovery-ownership) |
| R2-03 High | Matching unrelated provider satisfies dependency; unchanged incoming client is broken | Exact provider binding and full affected graph, including external consumers/resources; immutable disclosed scope and authorization; [dependencies](DETAILED_DESIGN.md#dependency-resolution-and-incoming-consumers) |
| R2-04 High | Application alias routes coordinator/executor through normal update | Protected profile roles resolved before dispatch; ordinary Web/CLI/MCP rejects them; [ownership](EXECUTION_RECOVERY.md#action-dispatch-and-recovery-ownership) |
| R2-05 High | Stopped coordinator returns during handoff; ordinary CLI is advertised as outage-independent | Stable controller-owned monotonic authority epoch, host confirmations, new epoch on binary rollback; separate recovery CLI/inspector; [handoff](EXECUTION_RECOVERY.md#coordinator-epoch-and-interface-availability) |

## Final consistency pass

| ID / priority | Gap | Correction |
| --- | --- | --- |
| F-01 High | Safe failure/cancel releases lack a durable completion contract; unknown finalization could resume the wrong phase | Local release receipts plus terminal coordinator transaction; incomplete evidence stays blocked; reconciliation follows original recorded action/step graph; [finalization](EXECUTION_RECOVERY.md#safe-failure-and-cancellation-finalization) |
| F-02 Medium | Recovery planning omits the request key required by plan-creation semantics | Recovery plan arguments include request key and explicit verify_recovery/recover action; [MCP catalog](MCP_API.md#tool-proposals) |

After these corrections, the final document-level pass found no further required change within this design scope. This does not certify runtime behavior or completeness of private deployment contracts.

## Documentation verification

Checked 20 Markdown files, 120 relative links/anchors, 4 fenced JSON examples and 31 table blocks. All checks passed with no missing links/anchors, JSON parse errors, whitespace/fence errors or inconsistent table widths. Added 21 future acceptance cases.

Compared the seven plan actions with the dispatch table and the state-diagram transitions with declared Job states. Also checked 18 cross-contract invariants for plan/operation identity, durable maintenance, step barriers, finalization, recovery/action separation, protected aliases, authority epochs, control-state compatibility, runner enums, scratch isolation, dependency binding and dedicated-Web/implementation-hold wording. These are static documentation checks, not protocol implementation tests.

- Parse fenced JSON as illustrative examples, not executable release/schema fixtures.
- Check relative files/anchors, final newlines, whitespace, fences and tables.
- Check action/state/result vocabulary and required cross-contract invariants.
- Confirm the change contains Markdown only and preserves non-document base files.
- Check public portability, dedicated Web ownership and explicit implementation hold.

## Remaining implementation and adoption gates

The [adoption work packages](ADOPTION.md) still require real application maintenance/startup contracts, exact provider/consumer/resource/writer mappings, trust provisioning and controller bootstrap. Unsupported isolation/fencing/compatibility is a plan blocker, not a best-effort update.

Future implementation must exercise [acceptance counterexamples](ACCEPTANCE.md) with fake providers, isolated resources and crash/duplicate/fault injection, then separately validate live enrollment. No runtime tests, migrations, CI changes, signing, provider calls, application-repository changes or host operations were performed by this loop.
