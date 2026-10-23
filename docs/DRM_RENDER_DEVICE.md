# Optional DRM render device in managed Docker applications

`DockerApplication.drm_render_node` is an optional, initially configured absolute
`/dev/dri/renderDNNN` path. Empty preserves ordinary CPU containers. The application
recipe owns this declaration; Web/MCP callers still supply only recipe settings.
No arbitrary Docker arguments, display/card/control nodes, privileged containers,
device requests or broad `/dev` mount are added.

Preflight and startup inspect root-owned non-symlink device directories and a
root-owned character device with DRM major 226 and render minor 128..255 matching
the selected filename. A non-root render group must have read/write access.
Updater passes that exact node with `rw` and adds its observed numeric group to
the existing non-root container user. It never changes device ownership, modes,
kernel/driver settings or host group membership. Runtime verification checks exact
Docker Devices/GroupAdd and refuses privileged/DeviceRequests drift. Updates retain
the original operator selection in the application profile/settings.

This is device access, not GPU codec/driver certification, runtime scheduling or
GPU ownership. The owning application must probe the actual operation and report
its backend. Server Manager remains the source for live observations. Existing
released Updater builds without this field cannot install a recipe using it;
publish/install a matching Updater release before deploying such an application.

Tests use injected device metadata/command observations; physical DRM and Docker
acceptance remains separate. No real host device or service was changed.
