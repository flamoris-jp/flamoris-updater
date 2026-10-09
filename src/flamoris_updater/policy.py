from flamoris_update_core.errors import UpdateError
from flamoris_update_core.inventory import DeploymentProfile, Observation
from flamoris_update_core.wire import version

SUPPORTED_MANAGED_VERSIONS = {"flamoris-gpu-node-manager": "1.2.0", "flamoris-updater": "1.0.0"}


def verify_managed_release(profile: DeploymentProfile, observation: Observation, action: str):
    if action == "install":
        return
    minimum = SUPPORTED_MANAGED_VERSIONS.get(profile.application_id, "1.0.0")
    if (
        observation.manifest_digest is None
        or observation.release is None
        or version(observation.release) < version(minimum)
    ):
        raise UpdateError(
            "unsupported_entry", "No supported Updater-managed installation is available"
        )
