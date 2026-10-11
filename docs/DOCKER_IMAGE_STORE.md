# Docker image identity and stage recovery

Classic Docker normally identifies an image by its config digest. The containerd
store can expose a manifest/index digest instead. Updater 1.0.7 verifies the
catalog's exact image content, then records Docker's actual immutable runtime ID
for creation, first setup, health verification and cleanup.

When catalog-ID inspection fails, only references from that successful
`docker load` are considered. Updater exports each candidate into a private
temporary archive and reads bounded config blobs without extracting paths.
The config SHA-256 must match the catalog ID. Linux/CPU, app/version labels,
anonymous-volume absence and the embedded Generation Controller are also checked.
The export is removed afterward; this fallback needs temporary image-export
space. Timeouts/other failures remain blocking outcomes.

Changing Docker storage backends or rewriting published catalogs is unnecessary.
Do not clear failed Jobs or retry the whole install blindly.

## Offline stage-only recovery

This administrator procedure covers only recorded Docker fresh installs without
databases stopped at image staging before container creation. Existing artifacts,
settings, copied configuration, directory metadata and original profile digest
must match. The target container/listener must be absent, with no other active or
uncertain Jobs. It does not import applications, replay DB operations or restore
data.

1. Inspect current Server Manager state, failed Job/log/layout, the actual three
   Updater units, `ExecStart`, runtime and setup path. Never infer host paths.
2. Obtain and checksum-verify the reviewed 1.0.7 bundle from Updater's release.
   Stage outside the active installation. Its recovery launcher uses that new
   bundle's indexed modules, independently of the active 1.0.6 installation.
3. Confirm no running Jobs and stop the observed Web, manager and supervisor
   units. Preserve all journals/configuration; other apps and Docker keep running.
4. Run the new bundle's recovery launcher without `--apply` first:

   ```bash
   sudo /absolute/new-bundle/bin/flamoris-updater-docker-recovery \
     --setup /absolute/observed/setup.json --job job-EXACT_FAILED_ID \
     --web-unit flamoris-updater.service \
     --manager-unit flamoris-updater-manager.service \
     --supervisor-unit flamoris-updater-supervisor.service
   ```

5. After verified preconditions, repeat with `--apply`. It validates inputs again,
   stages/verifies the image, creates a stopped container and records
   `awaiting_setup` in the original Job, retaining its failed timeline. It never
   recopies configuration, regenerates secrets or initializes a database.
6. Restart manager, supervisor and Web explicitly. Start first setup and verify
   app health in the screen. Register the Updater 1.0.7 release catalog and use
   normal self-update for the active Updater installation.

An uncertain container-create outcome remains `recovery_required` and cannot use
this stage-only procedure again. The script refuses running/missing Updater
services and never changes their executables or unrelated blockers.
