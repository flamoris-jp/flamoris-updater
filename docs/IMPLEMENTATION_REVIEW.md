# Implementation review and verification

Date: 2026-10-08. Scope: Updater-owned v1 source, deterministic tests, packaging/CI and dedicated Web. Reviewed the implemented source against the earlier [design review](REVIEW_LOOP_2026-10-08.md), then fixed counterexamples and added regression tests. No external reviewer or real-host certification is claimed.

## Round 1: execution and restoration

| Counterexample | Correction and regression evidence |
| --- | --- |
| A lost execute reply admits another Job | Immutable plan consumption across grants/callers/request keys; execution/interface tests |
| A lost effect reply or crash repeats a committed migration | Durable exported intent before effect, immutable operation binding, unknown tombstones; execution tests and actual isolated SQLite migration crash test |
| Signed plan omits backup, stopping or validation | Host independently validates complete safety phase coverage and transitive global barriers before any effects; adversarial signed-plan tests |
| Shared consumers migrate an owner's DB or disagree on schemas | Physical owner/writer registry, shared target/observed-vector consistency, only owner migration/snapshot resources, consumers stop first and providers start first; shared-resource test |
| Apparent idle owner is insufficient evidence | Fresh nonce/time inspection, profile/physical namespace binding, durable maintenance epochs, explicit operation proofs and predecessor receipts; execution and identity-drift tests |
| Backup creation is mistaken for recoverability | Separate isolated restore verification/proofs before migration, same-owner snapshot equality and original-parent snapshot checks; execution/recovery tests |
| Recovery releases blockers before global acceptance | Frozen parent, protected local transfer, global ownership CAS, final inventory/local resolution before one global transaction; linked recovery tests |
| Controller crashes after all child effects but before final acceptance | Resume only final publication with current authority/inventory checks, no new epoch or repeated owner effect; crash-at-finalizing regression |
| Normal cancellation changes a protected restoration Job | Protected recover action rejected by ordinary cancel admission |

## Round 2: trust, self-update and distribution

| Counterexample | Correction and regression evidence |
| --- | --- |
| One application/release maps to different platform manifests | One immutable signed root with bounded unique `artifact_variants`; platform selection leaves raw root identity unchanged |
| Boolean protocol version equals integer 1; disabled initializer includes null handlers | Strict pre-validation rejects boolean/float protocol fields and disabled initializer payload extras |
| Rotated valid catalog signature leaves cached old key binding | Same exact catalog bytes may accept a new valid detached signature; lower sequence/equal-sequence different bytes and release remapping rejected |
| Large escaped notes exceed transport size or repeat cursor | Character-safe bounded chunks, aggregate escaped-byte limits and catalog/range-bound offsets; large escaped-notes reconstruction test |
| A root Docker invocation selects another daemon | Explicit configured local daemon socket plus fixed private Docker config; anonymous image volumes rejected, healthchecks disabled and sensitive host mounts refused |
| Self approval remains valid after epoch/account changes | Preview binds current epoch, previous accepted target and operator revision; recheck scope/config/trust at protected phases; stale/revision tests |
| Failed staging is retried as a fresh self effect | Atomically gated durable self intent and unknown result, idempotent lookup; pre-stop crash and staging failure regressions |
| Next self operation uses obsolete bootstrap target | Accepted coordinator Manifest persisted in protected control inventory; next-plan regression |
| Candidate silently accepts an unknown control format/table | Read-only stdlib probe checks format/table/column versions and hashes all authoritative control records; no control DB restoration |
| Helper/controller stops itself while holding its own intent | Self commands restricted to coordinator role; executor/recovery-controller replacement requires separate bootstrap maintenance in v1 |
| JSONL export consumes unbounded memory or inspector ignores gaps | Streaming atomic export, read-only event-chain check and export validity/lag, bounded summaries/counts; corruption/lag regression |
| Web mistakes partial notes pagination for missing history or shows old inventory as fresh | Separate missing-history indicator and stale observation wording; static assets and session APIs checked |
| Initial GitHub workflow cannot parse colon in command | Block scalar YAML commands; both platform build/verification jobs rerun successfully |

## Automated verification

`pytest -q` exercises strict wire/models/routes, scoped authorization, duplicate requests/operations, seven lost-response phases, intent crash, cancellation, SDK Streamable HTTP negotiation and all 14 tool schemas, dedicated Web login/CSRF/session/rate limits, Native archive/digest/index confinement, OCI platform/config/layers/diff IDs, independent compatibility and protected recovery/self handoff. Standalone migration tests use a real isolated SQLite database and preserve its original row across a direct schema 1 → 3 transaction.

Peer credential tests use real local Unix socket pairs with allowed/denied UID admission; external owners and lifecycle commands are isolated test adapters. `ruff`, wheel/sdist build, schema export, documentation links and Native bundle verification are separate checks. Bundle verification stages with the production Native stager and launches all five indexed CLI entry points. GitHub CI builds/verifies Linux amd64 and arm64 independently. See [progress](../PROGRESS.md) for the final test count/checkpoint.

The manual signing workflow was reviewed, but not run: no production key, Environment or release tag was provisioned. No release or catalog was published.

## Supported boundaries and remaining acceptance

- Application-specific migration/lifecycle/backup/domain owners, Server/GPU Manager adapters and baseline entry transformations belong to adoption owners. Their production proof correctness is not established by test doubles.
- Live systemd, Docker daemon/registry, TLS/peer provisioning, independent service availability, real snapshots/restore, actual disk exhaustion and multi-host network/power failure scenarios remain [acceptance work](ACCEPTANCE.md). Source quotas are bounded; journal capacity/reserve and retention need deployment monitoring. No automatic capacity monitor or journal pruning is supplied.
- Root helper/executor and the stable recovery-controller cannot use coordinator self-update. Separate independently recoverable bootstrap maintenance is required; unsupported handoff is a blocker.
- v1 control schema is format 1 only; no startup migration, automatic failover, lease-expiry takeover, reverse migration or atomic multi-host rollback is supplied. Unknown effects stay blocked for reconciliation.
- Direct OCI retrieval supports configured mTLS registries. External bearer-auth registry negotiation and application-provided arbitrary command adapters are outside v1.
- Clock health is provisioned, with wall/monotonic drift detection. Secure configuration ancestors, Python interpreter, units, keys and persistent journal storage remain audited deployment prerequisites.
- Web is served and API-tested with inert bundled assets. Interactive browser/accessibility acceptance on the deployment origin remains a live gate; no visual/browser certification is claimed.
- Public documentation and release notes use portable examples. No production inventory, credentials, private hostnames or actual rollout are included.
