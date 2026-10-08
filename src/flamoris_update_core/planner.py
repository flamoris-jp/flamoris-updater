import uuid

from .errors import UpdateError
from .graph import ordered, route
from .inventory import DeploymentProfile, Observation, Resource, fingerprint
from .models import Manifest, Plan, Step
from .wire import digest, dumps, version


class Planner:
    def __init__(self, profiles: dict[str, DeploymentProfile], resources: dict[str, Resource]):
        self.profiles, self.resources = profiles, resources
        physical = {}
        for resource in resources.values():
            previous = physical.setdefault(resource.physical_binding_digest, resource.id)
            if (
                previous != resource.id
                or resource.owner_deployment not in profiles
                or not set(resource.writers) <= set(profiles)
            ):
                raise UpdateError("invalid_profile", "Physical resource ownership is ambiguous")
        for profile in profiles.values():
            if not set(profile.resources.values()) <= set(resources):
                raise UpdateError("invalid_profile")
            for resource_id in profile.resources.values():
                if profile.id not in resources[resource_id].writers:
                    raise UpdateError("invalid_profile", "Writer registration is incomplete")

    def affected(self, requested, action):
        selected = set(requested)
        if not selected <= set(self.profiles):
            raise UpdateError("invalid_input")
        if action in {"update", "recover"}:
            while True:
                before = set(selected)
                domains = {
                    self.resources[r].backup_domain
                    for i in selected
                    for r in self.profiles[i].resources.values()
                }
                for resource in self.resources.values():
                    if resource.backup_domain in domains:
                        selected.update(resource.writers)
                        selected.add(resource.owner_deployment)
                for identity, profile in self.profiles.items():
                    if set(profile.providers.values()) & selected:
                        selected.add(identity)
                if selected == before:
                    break
        return selected

    def inspected(self, requested, action):
        selected = self.affected(requested, action)
        pending = list(selected)
        while pending:
            for provider in self.profiles[pending.pop()].providers.values():
                if provider not in self.profiles:
                    raise UpdateError("incompatible_dependency")
                if provider not in selected:
                    selected.add(provider)
                    pending.append(provider)
        return selected

    def build(
        self,
        action: str,
        requested: dict[str, str],
        manifests: dict[str, Manifest],
        observed: dict[str, Observation],
        current: dict[str, Manifest],
        now: int,
        policy_revision: int,
        epoch: int,
        parent: str | None = None,
    ) -> Plan:
        if (
            action not in {"update", "install", "enroll", "verify_recovery", "recover"}
            or not requested
            or not set(requested) <= set(self.profiles)
        ):
            raise UpdateError("invalid_input")
        if action in {"recover", "verify_recovery"} and parent is None:
            raise UpdateError("invalid_input")
        selected = self.affected(requested, action)
        manifests = {
            i: m.select(self.profiles[i].platform, self.profiles[i].artifact_kind)
            for i, m in manifests.items()
        }
        # Include every affected shared-resource participant and incoming consumer.
        if action in {"update", "recover"}:
            while True:
                before = set(selected)
                affected_resources = {
                    r for i in selected for r in self.profiles[i].resources.values()
                }
                for resource_id in affected_resources:
                    resource = self.resources[resource_id]
                    selected.update(resource.writers)
                    selected.add(resource.owner_deployment)
                for identity, profile in self.profiles.items():
                    if set(profile.providers.values()) & selected:
                        selected.add(identity)
                if selected == before:
                    break
        if not selected <= set(observed) or not selected <= set(manifests):
            raise UpdateError(
                "incompatible_dependency", "Affected deployment evidence is incomplete"
            )
        targets = dict(requested)
        for identity in selected - set(targets):
            if observed[identity].manifest_digest is None:
                raise UpdateError("incompatible_dependency")
            targets[identity] = observed[identity].manifest_digest
        graph = {i: set() for i in selected}
        paths = {}
        shared_targets = {}
        shared_observed = {}
        for identity in selected:
            profile = self.profiles[identity]
            for logical, physical in profile.resources.items():
                target_schema = manifests[identity].schema_targets.get(logical)
                old = shared_targets.setdefault(physical, target_schema)
                actual = observed[identity].schemas.get(logical)
                prior = shared_observed.setdefault(physical, actual)
                if old != target_schema or prior != actual:
                    raise UpdateError("incompatible_dependency", "Shared resource schemas disagree")
                owner = self.resources[physical].owner_deployment
                if owner in selected and owner != identity:
                    graph[identity].add(owner)
        for identity in selected:
            profile, manifest, obs = (
                self.profiles[identity],
                manifests[identity],
                observed[identity],
            )
            if profile.role != "application":
                raise UpdateError(
                    "protected_target", "Protected authorities need their dedicated controller"
                )
            if (
                obs.application_id != profile.application_id
                or manifest.application_id != profile.application_id
                or obs.resource_bindings != profile.resources
                or obs.physical_binding_digests
                != {
                    r: self.resources[r].physical_binding_digest for r in profile.resources.values()
                }
                or obs.profile_digest != digest(dumps(profile))
                or manifest.artifact.platform != profile.platform
                or manifest.artifact.kind != profile.artifact_kind
            ):
                raise UpdateError("stale_plan", "Deployment identity or profile disagrees")
            if obs.active_work or obs.unknown_work:
                raise UpdateError("busy", "Application has active or unresolved work")
            if not profile.maintenance_startup or (
                profile.resources and not profile.isolated_restore
            ):
                raise UpdateError("quiescence_unavailable")
            if (
                manifest.lifecycle_profile.id != profile.lifecycle_profile
                or manifest.backup_profile.id != profile.backup_profile
                or not manifest.lifecycle_profile.admission_gate_required
            ):
                raise UpdateError("invalid_profile")
            if set(profile.resources) != set(manifest.schema_targets) or not set(
                profile.resources
            ) <= set(manifest.backup_profile.resource_classes):
                raise UpdateError("backup_unverified", "Resource backup scope is incomplete")
            if any(
                not self.resources[r].external_writers_fenced for r in profile.resources.values()
            ):
                raise UpdateError(
                    "quiescence_unavailable", "External writer contract is unavailable"
                )
            if action == "install":
                if (
                    obs.manifest_digest is not None
                    or set(obs.absent_resources) != set(profile.resources.values())
                    or not manifest.initialization.supported
                    or obs.schemas
                ):
                    raise UpdateError("not_empty")
                paths[identity] = []
            else:
                if obs.manifest_digest is None or obs.release is None:
                    raise UpdateError("unsupported_entry")
                if action == "update" and version(manifest.release) < version(obs.release):
                    raise UpdateError("unsupported_entry", "Automatic downgrade is excluded")
                starting_schemas = dict(obs.schemas)
                if action == "update":
                    for logical, physical in profile.resources.items():
                        if self.resources[physical].owner_deployment != identity:
                            starting_schemas[logical] = shared_targets[physical]
                paths[identity] = [] if action == "recover" else route(manifest, starting_schemas)
                if action in {"enroll", "verify_recovery"} and paths[identity]:
                    raise UpdateError(
                        "unsupported_migration", "Read-only action cannot transform schemas"
                    )
                if action == "enroll" and (
                    obs.entry_evidence is None or obs.manifest_digest != targets[identity]
                ):
                    raise UpdateError("unsupported_entry")
            by_id = {e.id: e for e in manifest.migrations}
            for edge_id in paths[identity]:
                edge = by_id[edge_id]
                if (
                    any(
                        self.resources[profile.resources[logical]].owner_deployment != identity
                        for logical in edge.affected_resources
                    )
                    or edge.runner_profile not in profile.runner_profiles
                    or edge.restore_profile not in profile.restore_profiles
                    or not edge.backup_required
                    or not manifest.recovery.data_restore
                ):
                    raise UpdateError("unsupported_migration")
            for dep in manifest.dependencies:
                if dep.kind == "component":
                    if profile.embedded_components.get(
                        dep.component_id
                    ) != dep.owner_application or not any(
                        c.id == dep.component_id and c.digest == dep.digest
                        for c in manifest.components
                    ):
                        raise UpdateError("incompatible_dependency")
                    continue
                provider_id = profile.providers.get(dep.interface_id)
                if provider_id is None or provider_id not in self.profiles:
                    raise UpdateError(
                        "incompatible_dependency", "Exact provider binding is missing"
                    )
                provider = (
                    manifests.get(provider_id)
                    if provider_id in selected
                    else current.get(provider_id)
                )
                if (
                    provider is None
                    or self.profiles[provider_id].application_id != dep.owner_application
                    or not any(
                        i.id == dep.interface_id and dep.range.accepts(i.version)
                        for i in provider.interfaces
                    )
                ):
                    raise UpdateError("incompatible_dependency")
                if provider_id in selected:
                    graph[identity].add(provider_id)
        activation = ordered(graph)
        steps = []
        frontier = []

        def phase(phase_name, operations):
            nonlocal frontier
            if not operations:
                return
            previous = list(frontier)
            frontier = []
            for identity, operation, args in operations:
                profile = self.profiles[identity]
                if operation not in profile.operations:
                    raise UpdateError(
                        "quiescence_unavailable", "Required owner operation is unavailable"
                    )
                step_id = f"step-{len(steps):04d}"
                steps.append(
                    Step(
                        id=step_id,
                        deployment_id=identity,
                        host_id=profile.host_id,
                        phase=phase_name,
                        operation=operation,
                        resources=sorted(profile.resources.values()),
                        predecessors=list(previous),
                        arguments=args,
                    )
                )
                frontier.append(step_id)

        phase("preparing", [(i, "prepare", {}) for i in sorted(selected)])
        if action in {"enroll", "verify_recovery"}:
            phase(
                "validating",
                [
                    (i, "validate", {"schemas": manifests[i].schema_targets, "read_only": True})
                    for i in sorted(selected)
                ],
            )
        else:
            phase("prepared", [(i, "begin", {}) for i in sorted(selected)])
            phase("quiescing", [(i, "close_admission", {}) for i in sorted(selected)])
            phase("quiescing", [(i, "drain", {}) for i in sorted(selected)])
            for identity in reversed(activation):
                phase("quiescing", [(identity, "stop", {})])
            backup_owners = sorted(
                {
                    self.resources[r].owner_deployment
                    for i in selected
                    for r in self.profiles[i].resources.values()
                }
            )
            phase("backing_up", [(i, "snapshot", {}) for i in backup_owners])
            phase("backing_up", [(i, "restore_verify", {}) for i in backup_owners])
            if action == "recover":
                phase(
                    "migrating", [(i, "restore", {"parent_job_id": parent}) for i in backup_owners]
                )
                phase(
                    "validating",
                    [
                        (i, "verify_restored_state", {"parent_job_id": parent})
                        for i in backup_owners
                    ],
                )
            else:
                for identity in activation:
                    manifest = manifests[identity]
                    if action == "install":
                        phase(
                            "migrating",
                            [(identity, "initialize", manifest.initialization.model_dump())],
                        )
                    else:
                        for edge_id in paths[identity]:
                            edge = next(e for e in manifest.migrations if e.id == edge_id)
                            phase(
                                "migrating",
                                [(identity, "apply_step", edge.model_dump(by_alias=True))],
                            )
            for identity in activation:
                phase("activating", [(identity, "activate", {})])
            phase(
                "validating",
                [
                    (i, "validate", {"schemas": manifests[i].schema_targets, "read_only": False})
                    for i in sorted(selected)
                ],
            )
            for identity in activation:
                phase("reopening", [(identity, "reopen_admission", {})])
        phase(
            "finalizing",
            [
                (i, "release", {"read_only": action in {"enroll", "verify_recovery"}})
                for i in sorted(selected)
            ],
        )
        return Plan(
            id="plan-" + uuid.uuid4().hex,
            action=action,
            targets=targets,
            resources=sorted({r for i in selected for r in self.profiles[i].resources.values()}),
            hosts=sorted({self.profiles[i].host_id for i in selected}),
            previous_targets={i: observed[i].manifest_digest for i in selected},
            previous_schemas={i: observed[i].schemas for i in selected},
            observations={i: fingerprint(observed[i]) for i in sorted(selected)},
            profile_digests={i: digest(dumps(self.profiles[i])) for i in selected},
            policy_revision=policy_revision,
            coordinator_epoch=epoch,
            created_at=now,
            expires_at=now + 900,
            steps=steps,
            parent_job_id=parent,
        )
