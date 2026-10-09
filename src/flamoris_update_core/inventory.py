from typing import Literal

from pydantic import Field, model_validator

from .models import ID, Digest, Model, Op, Schema


class Resource(Model):
    id: ID
    owner_deployment: ID
    writers: list[ID] = Field(min_length=1, max_length=128)
    backup_domain: ID
    physical_binding_digest: Digest
    external_writers_fenced: bool


class DeploymentProfile(Model):
    id: ID
    application_id: ID
    host_id: ID
    role: Literal["application", "coordinator", "executor", "recovery-controller"]
    platform: Literal["linux/amd64", "linux/arm64"]
    artifact_kind: Literal["native", "docker"]
    resources: dict[ID, ID]
    providers: dict[ID, ID]
    embedded_components: dict[ID, ID] = Field(default_factory=dict)
    operations: list[Op]
    lifecycle_profile: ID
    backup_profile: ID
    runner_profiles: list[ID]
    restore_profiles: list[ID]
    binding_revision: Digest
    maintenance_startup: bool
    isolated_restore: bool

    @model_validator(mode="after")
    def aliases(self):
        if len(set(self.resources.values())) != len(self.resources):
            raise ValueError("ambiguous resource aliases")
        return self


class Observation(Model):
    deployment_id: ID
    application_id: ID
    manifest_digest: Digest | None
    release: str | None
    schemas: dict[ID, Schema]
    resource_bindings: dict[ID, ID]
    physical_binding_digests: dict[ID, Digest] = Field(default_factory=dict)
    observed_at: int = Field(default=0, ge=0)
    observation_id: ID | None = None
    profile_digest: Digest
    config_revision: Digest
    journal_revision: int = Field(ge=0)
    active_work: bool
    unknown_work: bool
    evidence: list[ID] = Field(min_length=1)
    absent_resources: list[ID]
    maintenance_epoch: int = Field(ge=0)


def fingerprint(observation: Observation) -> str:
    from .wire import digest, dumps

    payload = observation.model_dump(
        exclude={"evidence", "journal_revision", "observed_at", "observation_id"}
    )
    return digest(dumps(payload))
