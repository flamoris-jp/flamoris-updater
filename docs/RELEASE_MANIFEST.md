> Historical design/integration record. The current simple flow is in [running](RUNNING.md) and [installation](INSTALL.md). Backup/restore, unmanaged import and client PKI requirements/examples below are superseded and are not accepted current contracts. Publication/full-host acceptance do not gate controlled installation tests.

# Release Manifest v1 design

**Reviewed v1 contract with strict loader implementation.** Shortened-digest JSON examples remain illustrative. Actual models/exported schemas and [running](RUNNING.md) define accepted fields.

## Wire representation and validation

`release.json` is UTF-8 JSON: object at the root, no duplicate keys, non-finite numbers or unknown fields. Maximum bytes: 1 MiB; nesting: 16; migration steps: 256; components: 128; dependencies: 128. Arrays with identity fields reject duplicate identities. Versions and schema IDs are strings; integer/float coercion is forbidden.

Reject unsupported Manifest versions before planning. Validate required fields and cross-references before using any content. Unknown future fields need a new schema version; do not silently interpret them.

`manifest_version` is integer 1. Releases/APIs use stable `major.minor.patch` SemVer with nonnegative decimal components, no leading zeros except zero itself, no prerelease/build suffix and no leading `v`; Git tags may use `v1.0`. A signed release declares the exact tag/revision mapping. Package versions are separately reported and never inferred from tags.

v1 compatibility constraints use only `min_inclusive` and `max_exclusive`, both normalized stable versions; no wildcard, expression parser or prerelease candidate selection. A dependency can require an exact component digest. Prereleases and automatic downgrades are excluded from v1 execution.

Schemas are opaque nonempty IDs up to 128 ASCII characters, not release SemVer. Existing application schema chains retain their original IDs.

## Required sections

| Field | Definition |
| --- | --- |
| `manifest_version` | 1 |
| `application_id`, `release`, `source` | Stable catalog application ID, normalized release and repository/tag/full revision |
| `artifact` | Kind, platform, immutable locator, digest, maximum expanded bytes and content index |
| `components` | Embedded package IDs, package versions and immutable source/digests |
| `interfaces` | Provided named API contracts/versions |
| `dependencies` | Required interface owner/range or embedded component identity |
| `schema_targets` | Target opaque schemas for logical application resource names |
| `migrations` | Directed transition graph with handler, preconditions, affected resources and recovery contract |
| `lifecycle_profile` | Profile ID, restart and validation/admission requirements |
| `backup_profile` | Profile ID and required persistent resource classes |
| `recovery` | Artifact-only/data-restore support and compatible previous-schema conditions |
| `initialization` | Explicit supported empty-state handler and target schemas, or unsupported |
| `release_notes` | Digests/locators for human notes and machine-readable changes |

Application/resource/handler/profile IDs reference operator-registered contracts. They never resolve caller-controlled executable paths, arbitrary commands, secrets, unit names, DB URLs or hostnames.

## Illustrative release

The IDs, digests and source below are fictitious. The shortened placeholder digests would be rejected by the production validator.

```json
{
  "manifest_version": 1,
  "application_id": "example-agent",
  "release": "1.2.0",
  "source": {
    "repository": "example/example-agent",
    "tag": "v1.2.0",
    "revision": "illustrative-full-revision"
  },
  "artifact": {
    "kind": "docker",
    "platform": "linux/amd64",
    "locator": "registry.example.invalid/example-agent@sha256:EXAMPLE",
    "digest": "sha256:EXAMPLE",
    "max_expanded_bytes": 1073741824,
    "content_index_digest": "sha256:EXAMPLE"
  },
  "components": [],
  "interfaces": [{"id": "agent-api", "version": "1.1.0"}],
  "dependencies": [{
    "kind": "interface",
    "owner_application": "example-intelligence",
    "interface_id": "intelligence-api",
    "range": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}
  }],
  "schema_targets": {"config": "cfg-3", "database": "db-7"},
  "migrations": [{
    "id": "cfg-1-to-3",
    "from": {"config": "cfg-1"},
    "to": {"config": "cfg-3"},
    "requires": {"database": "db-7"},
    "handler_id": "cfg_1_to_3",
    "runner_profile": "offline-migration-v1",
    "reconcile_handler_id": "cfg_1_to_3_reconcile",
    "affected_resources": ["config"],
    "backup_required": true,
    "retry_policy": "after_verified_not_applied",
    "restore_profile": "config-restore-v1"
  }],
  "lifecycle_profile": {
    "id": "agent-lifecycle-v1",
    "restart_required": true,
    "admission_gate_required": true,
    "validation_profiles": ["agent-health-v1"]
  },
  "backup_profile": {
    "id": "agent-backup-v1",
    "resource_classes": ["config", "database", "persistent-data"]
  },
  "recovery": {
    "artifact_only": false,
    "data_restore": true,
    "previous_schema_constraints": {"config": ["cfg-1"], "database": ["db-7"]}
  },
  "initialization": {"supported": false},
  "release_notes": {
    "human": {"locator": "release-notes.md", "digest": "sha256:EXAMPLE"},
    "changes": {"locator": "changes.json", "digest": "sha256:EXAMPLE"}
  }
}
```

This example declares only one config edge; it supports only databases already at db-7. Real releases must ship supported edges for all intended inspected starting states. Unsupported routes are rejected rather than invented.

## Artifact packaging

Docker: locator contains an immutable OCI digest. Record and verify the selected platform manifest/image identity as well as any enclosing index; the signature binds the index digest and verified index membership binds the chosen platform digest. Approved Compose/service definitions come from the local host profile; a downloaded Compose file cannot add host mounts, privileged mode or Docker socket access.

Native: CI supplies a versioned bundle with the interpreter/dependencies needed for the target platform. Installation extracts to a new inactive release directory, never over the active tree. The content index binds executable/module paths and hashes. Reject traversal, absolute names, devices, ownership surprises, duplicate paths and symlink/hardlink escape. Enforce compressed and expanded size/count limits.

Migration executables/modules, validators and initializers are content-indexed members of the signed artifact. Docker migrations run a pinned one-shot image with a fixed entrypoint/profile; Native migrations run the indexed runner from the staged artifact. Host policy must authorize both the publisher and the relevant handler profile.

## Trust and distribution

Sign exact `release.json` bytes; no JSON canonicalization is required for the release signature. A detached `release.sig.json` contains `signature_version:1`, `algorithm:"ed25519"`, `key_id`, Manifest SHA-256 and base64 signature. Unknown keys/algorithms and malformed length/encoding are rejected. Re-serializing the Manifest invalidates its signature.

Trusted public keys, application/channel scope, allowed download origins, host policy and revocation epochs are installed through the operator's protected trust configuration. A key advertised inside a release does not become trusted. Rotation adds the new key through that independent operator path, allows a bounded overlap, then revokes the old key. Recheck revocation at admission and before activation.

CI signs through an isolated release-signing role after build/verification. Hosts receive public keys only. Provisioning the first signing key and the CI signing integration is an implementation task; no signing secret exists in this repository.

The signed Manifest binds artifacts and human/structured notes by digest. The signed release catalog binds application/channel, monotonically increasing catalog sequence, expiry and release/Manifest digests. Persist the highest accepted sequence and its exact catalog digest. Lower sequences are rejected for new planning/admission; the same sequence with the identical digest is valid re-observation, while the same sequence with a different digest is equivocation and is rejected. Expired catalogs reject new planning/admission. Withdrawn releases remain in history but cannot be new targets. Already prepared content does not override withdrawal/revocation at activation.

Downloads are limited to profile-approved HTTPS/OCI origins. Reject redirects outside the approved origin, local metadata destinations and user-provided arbitrary URLs. Credentials are injected from protected host/coordinator stores, never from Manifest fields.

## Release notes and structured changes

`changes.json` declares format version 1, application/release, ordered entries with category (`feature|fix|compatibility|migration|security|known_issue`), summary, affected interface/resource and breaking flag; it also declares restart and recovery conditions. Free text is rendered as inert escaped/sanitized content, never instructions, scripts or active HTML.

Cumulative notes include every verified published release in the range `installed < release <= target`, including withdrawn intermediates marked as withdrawn, ordered by version. Package-component changes belong to the containing application notes. Missing or unverifiable historical notes are displayed as incomplete, never silently represented as a complete changelog. Missing notes for the target reject its release validation.

## Catalog and envelope fields

The signed catalog uses the same exact-byte detached signature envelope as a release. Its root fields are `catalog_version:1`, application/channel IDs, positive sequence, UTC expiry and bounded release entries (release, Manifest locator/digest, published-at, withdrawn flag and signed reason). Trust keys are independently scoped to catalog or release signing. Expiry requires a trustworthy local clock; unknown clock health rejects new admission.

For a known release version, a different Manifest digest is an immutable-release conflict, not an overwrite. Published history remains addressable by its original digest.

A plan binds the minimum accepted catalog sequence and exact target digests. A newer verified catalog may confirm the same unwithdrawn digests without altering authorization. Catalog expiry can be resolved by a fresh trusted catalog confirming those identities. Changed/withdrawn targets, revoked signing keys or changed applicable host policy block further activation; fresh content does not authorize a different plan.

Optional deployment facts are not release defaults: schema_targets may omit resource classes the application does not own, but local inventory must prove the omission. Newly discovered owned resources reject incomplete backup/validation scope.

## Optional fields and initializer shape

The only optional root extension in v1 is `preferred_routes`: a bounded list of starting schema vectors and ordered migration edge IDs. It may resolve path ambiguity only when the whole listed route passes the same compatibility/recovery validation. It cannot authorize unsupported edges or intermediate binaries.

`initialization.supported:false` permits no additional initializer fields. When true, require `handler_id`, `runner_profile`, `empty_validator_id`, resulting schema vector and `failed_initialization_recovery_profile`. Initialization cannot reuse a migration handler implicitly. The signed handler may create only profile-approved initially absent resources. Failed initialization preserves unknown/new data until the owner confirms a supported cleanup or repair; absence before install is not blanket permission to delete everything afterwards.

Contract identifiers use lowercase ASCII letters/digits plus dot, underscore or hyphen, at most 128 characters. Reject empty IDs, unrecognized enums, empty schema vectors where resources are owned, invalid digests/revisions and range endpoints with min >= max. Exact digest fields are lowercase `sha256:` plus 64 hex characters; source revisions declare the supported repository's full immutable object ID rather than a short hash.

## Sealed content and parser budgets

Release signature input is exact Manifest bytes; catalog signature input is exact catalog bytes. The verifier applies separately configured release/catalog key purposes and rejects cross-purpose key use even if both JSON documents can be parsed. Signature-envelope fields are strict, bounded and cannot select an unconfigured key or purpose.

After verification, staging/content indexes and release pointers are protected from application/runner writes. Native activation and rollback recheck the exact sealed artifact/content identity immediately before use and run only the profile-selected trusted interpreter/loader environment. Do not load a runner through writable search paths or caller-provided environment. Docker execution uses the verified platform digest, never a mutable tag.

Apply streaming byte limits before parsing/fetch buffering: release/catalog JSON 1 MiB each, signature envelope 16 KiB, each human/structured note 1 MiB, cumulative note response 2 MiB. Catalogs have at most 2048 entries, depth 16 and unique version/Manifest mappings; notes have bounded strings/entries/depth. Larger verified history is cursor-paginated, not concatenated without a limit. Artifact downloads/extraction also enforce profile-specific byte/file quotas independent of claimed release values.

Local notes locators are confined relative artifact paths; remote locators resolve only through the approved origin/profile. No absolute/traversing path, uncontrolled redirect or arbitrary URL is executable input.

## Implemented multi-platform root

`artifact` is the primary artifact; optional `artifact_variants` holds at most seven alternatives with unique `(kind, platform)`. One exact signed root and immutable application/release mapping covers both amd64 and arm64. `Manifest.select` chooses the profile-bound artifact view without changing the signed root digest. Release and catalog signatures have separate purposes. Same-byte catalog signature rotation is allowed; equal-sequence different bytes remain replay/equivocation. Cumulative notes use bounded character-safe chunks and catalog/range-bound cursors. See [implementation review](IMPLEMENTATION_REVIEW.md).
