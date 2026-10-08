# Roadmap

Updated 2026-10-08 after implementation authorization. Updater-owned v1 source work U1–U7 is implemented and covered by automated tests/CI. Publication, application adoption and real-host certification are separate gates.

| Work package | Source state | Remaining operational gate |
| --- | --- | --- |
| U1 Manifest/trust/catalog | Strict models, exact signatures, replay/rotation, bounded notes and multi-platform root | Provision keys, catalogs and approved origins |
| U2 Planner/schema/groups | Direct/full-vector routes, exact providers, shared owners/writers and ordered barriers | Verify live resource/dependency inventory |
| U3 Journal/authorization/Jobs | Durable intent, one consumed plan, scoped grants, unknown blockers and final acceptance | Certify persistent storage/capacity/crash behavior |
| U4 Native/Docker host execution | Bounded artifacts/processes, local profiles, mTLS/peer-checked helper | Audit real units/daemon/mounts and application owners |
| U5 Recovery/self-update | Linked restore and evidence-only child; protected coordinator handoff preserving current control store | Test real backups/fences/epochs; helper/controller replacement uses separate bootstrap |
| U6 MCP/CLI | Fourteen typed SDK tools, human grants, shared durable Jobs and stable inspector | Provision client identities/TLS and operator scopes |
| U7 Dedicated Web | Included static UI, independent Argon2/session/CSRF, plan/grant/Job/history flow | Browser/accessibility and real TLS/operator acceptance |
| A1 Application standalone entry migrations | Common runner provided; application-specific handlers outside this task | AI-side v0.1 → v1.0 and GPU Node Manager v1.1 → v1.2 independently accepted |
| A2 Application/release packaging/signing | Updater bundle and manual isolated signing-candidate workflow provided | Release Environment/keys/tag, publication and fresh signed catalog |
| D1 Initial install/enrollment | Procedure documented; no live change performed | Stable recovery install, audited profiles, entry receipts and full live acceptance |

[Implementation review](IMPLEMENTATION_REVIEW.md) records fixes and automated evidence; [acceptance](ACCEPTANCE.md) retains the real deployment matrix. A merged implementation is not proof of a published or accepted deployment. Web stays in this repository; Studio integration is outside scope.
