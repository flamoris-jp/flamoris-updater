# Application installation and update ownership

The former `flamoris-updater-entry` command and baseline-to-managed transition
have been removed. For an empty environment, install Updater first and follow
[fresh installation](INSTALL.md): AI-side 1.0.0, GPU Node Manager 1.2.0 directly.
Old 0.1/1.1 labels describe historical environments, not prerequisites.

The application lifecycle Owner is still used by the separate ordinary remote
update protocol. Applications own schemas, migrations and domain acceptance;
Updater owns orchestration. An Owner must remain available while its application
is stopped, and its resource bindings must cover exactly the application's owned
data/config/state. Shared runtimes, models and unrelated services are outside
those resources. See [migration](MIGRATION_CONTRACT.md),
[execution](EXECUTION_RECOVERY.md) and [running](RUNNING.md) contracts.

Historical standalone-transition receipt values remain readable for compatibility.
The removed command cannot create new receipts, and ordinary Owner activation
records `verified_adoption`. Fresh local installation does not produce or consume
standalone-transition evidence and does not yet enroll into that remote protocol.
