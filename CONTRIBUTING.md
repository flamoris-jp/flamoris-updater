# Contributing

Read [README](README.md), [AGENTS](AGENTS.md), [design](docs/DESIGN.md) and [progress](PROGRESS.md). Python 3.12 source, executable contracts, tests and CI are present. Release publication and live adoption have separate gates.

Use a focused branch and PR. Describe the concrete problem, resulting behavior, ownership boundaries, compatibility and validation. Run the README development checks, add meaningful deterministic failure tests for changed execution behavior and update PROGRESS/docs when state changes. Real-host mutations are separate acceptance work.

Core stays application/transport-neutral; FLAMORIS policy and application handlers belong to their respective owners. Web belongs to Updater and shares its coordinator with CLI/MCP. Inspect existing shared infrastructure before adding dependencies. Preserve lock constraints and both platform bundle builds when dependencies change.

Keep private topology, secrets, tokens, signing keys, sensitive data and raw provider output out of commits and public reports. Use existing Issue forms with sanitized evidence; follow [SECURITY](SECURITY.md) for security reports. Never infer live state from the roadmap.

Code is Apache-2.0 unless stated otherwise. Document compatible third-party licenses and preserve their distribution metadata.
