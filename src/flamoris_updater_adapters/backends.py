import time
import uuid
from pathlib import Path

import httpx

from flamoris_update_core.contracts import OwnerResult
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.inventory import Observation
from flamoris_update_core.wire import decode, digest, dumps

from .artifacts import origin
from .process import bounded_command


class RemoteOwner:
    def __init__(self, endpoint: str, client: httpx.Client):
        origin(endpoint)
        self.endpoint = endpoint.rstrip("/")
        self.client = client

    def _post(self, action: str, body: bytes):
        if len(body) > 1024 * 1024:
            raise UpdateError("invalid_input")
        try:
            with self.client.stream(
                "POST",
                self.endpoint + "/" + action,
                content=body,
                headers={"content-type": "application/json"},
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise UpdateError("outcome_unknown")
                parts, size = [], 0
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > 256 * 1024:
                        raise UpdateError("outcome_unknown")
                    parts.append(chunk)
                return b"".join(parts)
        except httpx.HTTPError:
            raise UpdateError("outcome_unknown", "Owner response is unavailable") from None

    def inspect(self, profile):
        nonce = "obs-" + uuid.uuid4().hex
        raw = self._post(
            "inspect",
            dumps(
                {
                    "contract_version": 1,
                    "observation_id": nonce,
                    "deployment_id": profile.id,
                    "resource_ids": sorted(profile.resources.values()),
                    "profile_digest": digest(dumps(profile)),
                }
            ),
        )
        result = decode(Observation, raw, 256 * 1024)
        if (
            result.observation_id != nonce
            or not int(time.time()) - 30 <= result.observed_at <= int(time.time()) + 5
            or result.deployment_id != profile.id
            or result.application_id != profile.application_id
            or result.profile_digest != digest(dumps(profile))
            or result.resource_bindings != profile.resources
        ):
            raise UpdateError("stale_plan")
        return result

    def perform(self, request):
        return decode(OwnerResult, self._post("operations", dumps(request)), 256 * 1024)


class NativeDriver:
    def __init__(
        self,
        store,
        unit: str,
        unit_file: Path,
        unit_digest: str,
        pointer: Path,
        command=bounded_command,
    ):
        self.store, self.unit, self.unit_file, self.unit_digest, self.pointer, self.command = (
            store,
            unit,
            Path(unit_file),
            unit_digest,
            Path(pointer),
            command,
        )

    def check_binding(self):
        import os
        import re

        if (
            not re.fullmatch(r"[a-zA-Z0-9_.@-]+\.service", self.unit)
            or self.unit_file.is_symlink()
            or self.unit_file.stat().st_uid != os.geteuid()
            or self.unit_file.stat().st_mode & 0o022
            or digest(self.unit_file.read_bytes()) != self.unit_digest
        ):
            raise UpdateError(
                "invalid_profile", "Service definition differs from protected binding"
            )
        result = self.command(
            [
                "/usr/bin/systemctl",
                "show",
                self.unit,
                "--property=FragmentPath",
                "--property=NeedDaemonReload",
            ]
        )
        values = dict(line.split("=", 1) for line in result.decode().splitlines() if "=" in line)
        if (
            values.get("FragmentPath") != str(self.unit_file)
            or values.get("NeedDaemonReload") != "no"
        ):
            raise UpdateError("invalid_profile")

    def prepare(self, manifest):
        self.check_binding()
        return self.store.prepare(manifest.artifact)

    def stop(self):
        self.check_binding()
        self.command(["/usr/bin/systemctl", "stop", self.unit])
        value = self.command(
            ["/usr/bin/systemctl", "show", self.unit, "--property=ActiveState", "--value"]
        ).strip()
        if value not in {b"inactive", b"failed"}:
            raise UpdateError("outcome_unknown")

    def activate(self, manifest, operation_id):
        self.check_binding()
        self.store.activate(manifest.artifact, self.pointer)
        self.command(["/usr/bin/systemctl", "start", self.unit])

    def verify_active(self, manifest, operation_id):
        self.check_binding()
        directory = self.store.root / manifest.artifact.digest.removeprefix("sha256:")
        if not self.pointer.is_symlink() or self.pointer.resolve() != directory.resolve():
            raise UpdateError("outcome_unknown")
        self.store.verify(directory, manifest.artifact)
        if (
            self.command(
                ["/usr/bin/systemctl", "show", self.unit, "--property=ActiveState", "--value"]
            ).strip()
            != b"active"
        ):
            raise UpdateError("outcome_unknown")

    def source_state(self):
        self.check_binding()
        state = self.command(
            ["/usr/bin/systemctl", "show", self.unit, "--property=ActiveState", "--value"]
        ).strip()
        if state not in {b"inactive", b"failed"} or not self.pointer.is_symlink():
            raise UpdateError("legacy_not_quiescent")
        return {
            "unit_digest": self.unit_digest,
            "pointer": str(self.pointer.resolve()),
            "state": state.decode(),
        }


class ApplicationBackend:
    def __init__(self, owners: dict[str, RemoteOwner], drivers: dict, activation_signer=None):
        self.owners, self.drivers, self.activation_signer = owners, drivers, activation_signer

    def inspect(self, profile):
        return self.owners[profile.id].inspect(profile)

    def prepare(self, profile, manifest):
        self.drivers[profile.id].prepare(manifest)

    def perform(self, profile, manifest, request):
        # Owner API covers data/maintenance; host profile covers executable lifecycle.
        if request.operation == "activate":
            if self.activation_signer is None:
                raise UpdateError("invalid_profile")
            self.drivers[profile.id].activate(manifest, request.operation_id)
            self.drivers[profile.id].verify_active(manifest, request.operation_id)
            activation = self.activation_signer.packet(
                {
                    "kind": "host_activation",
                    "application_id": request.application_id,
                    "deployment_id": request.deployment_id,
                    "artifact_digest": request.artifact_digest,
                    "manifest_digest": request.arguments["manifest_digest"],
                    "operation_id": request.operation_id,
                    "job_id": request.job_id,
                    "plan_digest": request.plan_digest,
                }
            )
            request = request.model_copy(
                update={"arguments": {**request.arguments, "host_activation": activation}}
            )
        result = self.owners[profile.id].perform(request)
        if request.operation == "stop" and result.outcome == "verified":
            from flamoris_update_core.contracts import verified

            verified(request, result)
            self.drivers[profile.id].stop()
        return result
