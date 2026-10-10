# Updating an already configured 1.0.3 installation

Version 1.0.3 has one catalog and no screen action to replace its URL after setup. Its existing self-update screen can select 1.0.4 only after that catalog contains the new recipe. Version 1.0.4 adds multiple repository catalog registration; it cannot retroactively add that action to the running 1.0.3 screen.

For an installation that has not completed its first setup, use the [initial-install catalog](../catalogs/README.md) during that existing setup. For an already configured installation, perform the following one-time operator maintenance, then use the ordinary self-update screen. Do not rerun bootstrap, create a new manager state or delete the original supervisor bundle.

The [maintenance script](../scripts/prepare_103_catalog.py) uses the installed 1.0.3 packages, verifies the exact published snapshot digest, and atomically changes the catalog source/snapshot and adds immutable release bindings. It preserves application/settings records, self-installation, Jobs, history and previous recipe bindings. It refuses unfinished/recovery Jobs, a different installed version, writable runtime ancestors or conflicting immutable recipes. It does not install payloads or modify configuration, units, app data or databases.

Place the reviewed script in a root-owned file/directory. Find the existing `setup.json` from the current systemd unit's `--config` argument and the original runtime from its `bootstrap_executable` entry. Use those actual absolute paths below; the examples are placeholders, not new installation locations.

1. Validate while the original services are running. Resolve any pending Job before proceeding:

   ```bash
   sudo /usr/bin/python3.12 -I /absolute/root-owned/prepare_103_catalog.py --runtime /absolute/original-1.0.3-bundle --config /absolute/existing/setup.json --check
   ```

2. Stop the idle manager and supervisor to prevent concurrent Jobs. The Web service remains available, with manager operations briefly unavailable:

   ```bash
   sudo systemctl stop flamoris-updater-manager.service flamoris-updater-supervisor.service
   ```

3. Run the same script without `--check`. It independently requires both units to be inactive and rechecks pending Jobs and immutable bindings:

   ```bash
   sudo /usr/bin/python3.12 -I /absolute/root-owned/prepare_103_catalog.py --runtime /absolute/original-1.0.3-bundle --config /absolute/existing/setup.json
   ```

4. Restart the original manager and supervisor, including if the previous command refused the switch:

   ```bash
   sudo systemctl start flamoris-updater-manager.service flamoris-updater-supervisor.service
   ```

5. Refresh the existing screen and select Updater 1.0.4. The original 1.0.3 login still applies until the update succeeds. After success, use the simplified screen to register the [individual repository catalogs](../catalogs/README.md).

The maintenance transaction and catalog parsing were verified against 1.0.3 source with isolated local journals, including unchanged history/settings and rejection before writes. This is not a real-host upgrade result; live unit paths, unfinished Jobs, runtime prerequisites and post-update health still require the normal host checks.
