> Transport update: the separate Owner service now uses a peer-checked local Unix socket. Prior certificate/listener configuration is unsupported; see [transport](TRANSPORT.md). Application SDK pins/artifacts still require coordinated updates.

# Application installation and update ownership

Existing unmanaged applications cannot be imported into Updater management.
The former entry CLI, registration tools/action/role and transition evidence
have been removed. AI applications target 1.0.0 and GPU Node Manager 1.2.0 directly.

The simple new installation, first setup and subsequent update connection remain
separate work. This document does not claim end-to-end installation acceptance.

## Application-owned resources

The following source contract inventory describes ordinary application ownership,
not resources that must be preserved when an operator chooses a clean install.

| Application | Required resource classes | Current accepted schema identifiers |
| --- | --- | --- |
| Agent | configuration, database | agent-config-1; 005_model_continuations |
| Studio | configuration, database, thumbnails | studio-config-1; 20261005_12; studio-thumbnails-1 |
| Intelligence | configuration | intelligence-config-1 |
| Controller / co-hosted Generation MCP | configuration, definitions, inputs, recipes, outputs | controller-config-1; comfy-definitions-retained-1; provider-inputs-1; generation-recipes-1; generation-state-2 |
| Hub | configuration | hub-catalog-1 |
| GPU Node Manager | configuration, evidence | gpu-profiles-1; runtime-evidence-1 |

Applications own schema migrations and domain validation. Normal updates keep
persistent configuration/data separate from executable releases. Controller is
embedded in Generation's deployment; external runtimes and models are outside
Updater's application resources. The common `flamoris-update-core` SDK remains
separate from the full coordinator's dependencies.

See [migration](MIGRATION_CONTRACT.md), [execution](EXECUTION_RECOVERY.md) and
[running](RUNNING.md) for the remaining managed-update contracts.
