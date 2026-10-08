from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .wire import version

ID = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$", max_length=128)]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Schema = Annotated[str, StringConstraints(pattern=r"^[\x21-\x7e]{1,128}$")]
Action = Literal[
    "update",
    "install",
    "enroll",
    "verify_recovery",
    "recover",
    "self_update",
    "executor_maintenance",
]
Phase = Literal[
    "accepted",
    "preparing",
    "prepared",
    "quiescing",
    "backing_up",
    "migrating",
    "activating",
    "validating",
    "reopening",
    "finalizing",
    "succeeded",
    "failed_safe",
    "cancelled_safe",
    "recovery_required",
    "unknown",
]
Op = Literal[
    "prepare",
    "begin",
    "close_admission",
    "drain",
    "stop",
    "snapshot",
    "restore_verify",
    "apply_step",
    "initialize",
    "activate",
    "validate",
    "reopen_admission",
    "release",
    "inspect",
    "reconcile",
    "restore",
    "verify_restored_state",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, populate_by_name=True)


class VersionRange(Model):
    min_inclusive: str
    max_exclusive: str

    @model_validator(mode="after")
    def bounds(self):
        if version(self.min_inclusive) >= version(self.max_exclusive):
            raise ValueError("empty range")
        return self

    def accepts(self, candidate: str) -> bool:
        return version(self.min_inclusive) <= version(candidate) < version(self.max_exclusive)


class Source(Model):
    repository: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    tag: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    revision: Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]


class Artifact(Model):
    kind: Literal["native", "docker"]
    platform: Literal["linux/amd64", "linux/arm64"]
    locator: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    digest: Digest
    max_expanded_bytes: int = Field(gt=0, le=2**50)
    content_index_digest: Digest

    @model_validator(mode="after")
    def immutable(self):
        if self.kind == "docker" and not self.locator.endswith("@" + self.digest):
            raise ValueError("Docker locator must bind exact digest")
        return self


class Component(Model):
    id: ID
    version: str
    source: Source
    digest: Digest


class Interface(Model):
    id: ID
    version: str

    @field_validator("version")
    @classmethod
    def semver(cls, value):
        version(value)
        return value


class Dependency(Model):
    kind: Literal["interface", "component"]
    owner_application: ID
    interface_id: ID | None = None
    component_id: ID | None = None
    range: VersionRange | None = None
    digest: Digest | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.kind == "interface":
            if (
                self.interface_id is None
                or self.range is None
                or self.component_id is not None
                or self.digest is not None
            ):
                raise ValueError("interface dependency shape")
        elif (
            self.component_id is None
            or self.digest is None
            or self.interface_id is not None
            or self.range is not None
        ):
            raise ValueError("component dependency shape")
        return self


class Edge(Model):
    id: ID
    source: dict[ID, Schema] = Field(alias="from", min_length=1)
    to: dict[ID, Schema] = Field(min_length=1)
    requires: dict[ID, Schema]
    handler_id: ID
    runner_profile: ID
    reconcile_handler_id: ID
    affected_resources: list[ID] = Field(min_length=1, max_length=128)
    backup_required: bool
    retry_policy: Literal["never", "after_verified_not_applied"]
    restore_profile: ID

    @model_validator(mode="after")
    def shape(self):
        if (
            set(self.source) != set(self.to)
            or set(self.to) != set(self.affected_resources)
            or self.source == self.to
        ):
            raise ValueError("edge must declare exactly its changed resources")
        if len(self.affected_resources) != len(set(self.affected_resources)):
            raise ValueError("duplicate resource")
        if set(self.source) & set(self.requires):
            raise ValueError("conflicting edge guards")
        return self


class LifecycleProfile(Model):
    id: ID
    restart_required: bool
    admission_gate_required: bool
    validation_profiles: list[ID] = Field(min_length=1, max_length=32)


class BackupProfile(Model):
    id: ID
    resource_classes: list[ID] = Field(max_length=128)


class RecoveryPolicy(Model):
    artifact_only: bool
    data_restore: bool
    previous_schema_constraints: dict[ID, list[Schema]]


class Initialization(Model):
    supported: bool
    handler_id: ID | None = None
    runner_profile: ID | None = None
    empty_validator_id: ID | None = None
    schema_targets: dict[ID, Schema] | None = None
    failed_initialization_recovery_profile: ID | None = None

    @model_validator(mode="after")
    def shape(self):
        fields = (
            self.handler_id,
            self.runner_profile,
            self.empty_validator_id,
            self.schema_targets,
            self.failed_initialization_recovery_profile,
        )
        if self.supported != all(x is not None for x in fields) or (
            not self.supported and any(x is not None for x in fields)
        ):
            raise ValueError("initializer shape")
        return self


class Note(Model):
    locator: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    digest: Digest


class Notes(Model):
    human: Note
    changes: Note


class PreferredRoute(Model):
    source: dict[ID, Schema] = Field(alias="from")
    edges: list[ID] = Field(min_length=1, max_length=256)


class Manifest(Model):
    manifest_version: Literal[1]
    application_id: ID
    release: str
    source: Source
    artifact: Artifact
    components: list[Component] = Field(max_length=128)
    interfaces: list[Interface] = Field(max_length=128)
    dependencies: list[Dependency] = Field(max_length=128)
    schema_targets: dict[ID, Schema]
    migrations: list[Edge] = Field(max_length=256)
    lifecycle_profile: LifecycleProfile
    backup_profile: BackupProfile
    recovery: RecoveryPolicy
    initialization: Initialization
    release_notes: Notes
    preferred_routes: list[PreferredRoute] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def consistency(self):
        version(self.release)
        for component in self.components:
            version(component.version)
        for items in (self.components, self.interfaces, self.migrations):
            if len({x.id for x in items}) != len(items):
                raise ValueError("duplicate identity")
        dep_ids = [
            (d.kind, d.owner_application, d.interface_id, d.component_id) for d in self.dependencies
        ]
        if len(set(dep_ids)) != len(dep_ids):
            raise ValueError("duplicate dependency")
        for edge in self.migrations:
            if not (set(edge.source) | set(edge.requires)) <= set(self.schema_targets):
                raise ValueError("unknown schema resource")
        for route in self.preferred_routes:
            if not set(route.edges) <= {e.id for e in self.migrations}:
                raise ValueError("unknown preferred edge")
        if (
            self.initialization.supported
            and self.initialization.schema_targets != self.schema_targets
        ):
            raise ValueError("initial schema target mismatch")
        return self


class Step(Model):
    id: ID
    deployment_id: ID
    host_id: ID
    phase: Phase
    operation: Op
    resources: list[ID]
    predecessors: list[ID]
    arguments: dict


class Plan(Model):
    plan_version: Literal[1] = 1
    id: ID
    action: Action
    targets: dict[ID, Digest]
    resources: list[ID]
    hosts: list[ID]
    observations: dict[ID, Digest]
    profile_digests: dict[ID, Digest]
    policy_revision: int = Field(ge=1)
    coordinator_epoch: int = Field(ge=1)
    created_at: int
    expires_at: int
    steps: list[Step] = Field(max_length=4096)
    parent_job_id: ID | None = None

    @model_validator(mode="after")
    def graph(self):
        known = set()
        for step in self.steps:
            if (
                step.id in known
                or not set(step.predecessors) <= known
                or step.deployment_id not in self.targets
                or step.host_id not in self.hosts
                or not set(step.resources) <= set(self.resources)
            ):
                raise ValueError("invalid step graph or scope")
            known.add(step.id)
        if not self.steps or self.expires_at <= self.created_at:
            raise ValueError("empty/expired plan")
        return self
