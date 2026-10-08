from flamoris_update_core.errors import UpdateError
from flamoris_update_core.inventory import DeploymentProfile, Observation
from flamoris_update_core.wire import version

ENTRY_VERSIONS = {"flamoris-gpu-node-manager": "1.2.0", "flamoris-updater": "1.0.0"}


def verify_entry(profile: DeploymentProfile, observation: Observation, action: str):
    if action == "install":
        return
    minimum = ENTRY_VERSIONS.get(profile.application_id, "1.0.0")
    if observation.release is None or version(observation.release) < version(minimum):
        raise UpdateError(
            "unsupported_entry", "Application-owned standalone entry transition is required"
        )
