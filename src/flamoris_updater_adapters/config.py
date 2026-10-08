import base64
import os
import ssl
import stat
import time
from pathlib import Path
from typing import Literal

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import Field, model_validator

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.inventory import DeploymentProfile, Resource
from flamoris_update_core.models import ID, Digest, Model
from flamoris_update_core.wire import decode

from .artifacts import origin
from .signing import Key, Signer


def protected_read(filename: str, private=False, root_only=False, limit=1024 * 1024) -> bytes:
    path = Path(filename)
    if not path.is_absolute():
        raise UpdateError("invalid_profile", "Protected paths must be absolute")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid not in ({0} if root_only else {0, os.geteuid()})
                or info.st_mode & (0o077 if private else 0o022)
                or info.st_size > limit
            ):
                raise UpdateError("unsafe_storage")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read(limit + 1)
        finally:
            os.close(descriptor)
    except OSError:
        raise UpdateError("unsafe_storage", "Protected file cannot be read") from None


class TLS(Model):
    ca_file: str
    cert_file: str
    key_file: str

    def context(self):
        protected_read(self.ca_file)
        protected_read(self.cert_file)
        protected_read(self.key_file, private=True)
        context = ssl.create_default_context(cafile=self.ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert_file, self.key_file)
        return context


class Endpoint(Model):
    url: str
    tls: TLS
    timeout_seconds: int = Field(default=120, ge=1, le=3600)

    @model_validator(mode="after")
    def secure(self):
        origin(self.url)
        return self

    def client(self):
        return httpx.Client(
            verify=self.tls.context(),
            timeout=self.timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        )


class PublicKey(Model):
    id: ID
    application_id: ID
    purpose: Literal["release", "catalog", "authority", "controller", "receipt"]
    public_base64: str
    revoked: bool = False
    channels: list[ID] = Field(default_factory=lambda: ["stable"])

    def key(self):
        try:
            raw = base64.b64decode(self.public_base64, validate=True)
            if len(raw) != 32:
                raise ValueError("key size")
            return Key(raw, self.application_id, self.purpose, self.revoked)
        except (ValueError, TypeError):
            raise UpdateError("invalid_profile", "Invalid pinned public key") from None


class ReleaseSource(Model):
    application_id: ID
    channel: ID = "stable"
    catalog_url: str
    catalog_signature_url: str
    origins: list[str] = Field(min_length=1, max_length=32)
    tls: TLS


class HostConnection(Model):
    host_id: ID
    endpoint: Endpoint


class Quota(Model):
    max_download_bytes: int = Field(gt=0, le=4 * 1024**3)
    max_expanded_bytes: int = Field(gt=0, le=16 * 1024**3)
    max_files: int = Field(gt=0, le=100000)
    reserve_bytes: int = Field(ge=16 * 1024**2)


class NativeBinding(Model):
    kind: Literal["native"]
    deployment_id: ID
    owner: Endpoint
    unit: str
    unit_file: str
    unit_digest: Digest
    active_pointer: str
    control_state_directory: str | None = None
    python_executable: str | None = None


class MountBinding(Model):
    source: str
    target: str
    read_only: bool


class PortBinding(Model):
    host_ip: str
    host_port: int = Field(gt=0, lt=65536)
    container_port: int = Field(gt=0, lt=65536)

    @model_validator(mode="after")
    def address(self):
        import ipaddress

        if ipaddress.ip_address(self.host_ip).version != 4:
            raise ValueError("Explicit IPv4 binding required")
        return self


class DockerBinding(Model):
    kind: Literal["docker"]
    deployment_id: ID
    owner: Endpoint
    container_name: ID
    registry_origin: str
    repository: str
    registry_tls: TLS
    docker_config_directory: str
    daemon_socket: str
    daemon_data_directory: str
    network: ID
    allow_host_network: bool = False
    ports: list[PortBinding] = Field(default_factory=list, max_length=64)
    runtime_user: str
    memory_bytes: int = Field(gt=0)
    pids_limit: int = Field(gt=0, le=65536)
    mounts: list[MountBinding] = Field(max_length=128)
    environment_file: str | None = None


class CoordinatorConfig(Model):
    config_version: Literal[1]
    domain_id: ID
    state_directory: str
    public_origin: str
    listen_host: str
    listen_port: int = Field(gt=0, lt=65536)
    server_tls: TLS | None = None
    trusted_loopback_proxy: bool = False
    profiles: list[DeploymentProfile] = Field(min_length=1, max_length=128)
    resources: list[Resource] = Field(max_length=2048)
    hosts: list[HostConnection] = Field(min_length=1, max_length=128)
    release_keys: list[PublicKey] = Field(min_length=1)
    receipt_keys: list[PublicKey] = Field(min_length=1)
    release_sources: list[ReleaseSource] = Field(default_factory=list)
    signer_id: ID
    signer_private_file: str
    policy_revision: int = Field(ge=1)
    clock_healthy: bool

    @model_validator(mode="after")
    def bounds(self):
        if origin(self.public_origin) != self.public_origin or (
            self.server_tls is None
            and (not self.trusted_loopback_proxy or self.listen_host not in {"127.0.0.1", "::1"})
        ):
            raise ValueError("HTTPS or explicit local TLS proxy is required")
        for items in (self.profiles, self.resources):
            if len({x.id for x in items}) != len(items):
                raise ValueError("duplicate identity")
        if len({h.host_id for h in self.hosts}) != len(self.hosts):
            raise ValueError("duplicate host")
        if not {p.host_id for p in self.profiles} <= {h.host_id for h in self.hosts}:
            raise ValueError("missing host")
        return self


class HelperConfig(Model):
    config_version: Literal[1]
    domain_id: ID
    host_id: ID
    state_directory: str
    socket_path: str
    socket_group_id: int = Field(ge=0)
    allowed_peer_uids: list[int] = Field(min_length=1, max_length=16)
    staging_directory: str
    profiles: list[DeploymentProfile] = Field(min_length=1, max_length=128)
    resources: list[Resource] = Field(max_length=2048)
    bindings: list[NativeBinding | DockerBinding] = Field(min_length=1, max_length=128)
    quota: Quota
    authorities: list[PublicKey] = Field(min_length=1)
    receipt_keys: list[PublicKey] = Field(min_length=1)
    release_keys: list[PublicKey] = Field(min_length=1)
    release_sources: list[ReleaseSource] = Field(min_length=1)
    signer_private_file: str
    clock_healthy: bool


class HostAPIConfig(Model):
    config_version: Literal[1]
    socket_path: str
    helper_timeout_seconds: int = Field(ge=1, le=3600)
    listen_host: str
    listen_port: int = Field(gt=0, lt=65536)
    server_tls: TLS


class Clock:
    def __init__(self, healthy: bool):
        if not healthy:
            raise UpdateError("clock_unknown")
        self.wall, self.monotonic = time.time(), time.monotonic()

    def __call__(self):
        now = time.time()
        if now < 1577836800 or abs((now - self.wall) - (time.monotonic() - self.monotonic)) > 5:
            raise UpdateError("clock_unknown")
        return int(now)


def signer(identity, filename):
    raw = protected_read(filename, private=True, limit=16 * 1024)
    if len(raw) == 32:
        return Signer(identity, raw)
    try:
        key = load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("wrong key algorithm")
        return Signer(identity, key.private_bytes_raw())
    except (ValueError, TypeError):
        raise UpdateError("invalid_profile", "Protected Ed25519 key is required") from None


def load(model, path, root_only=False):
    return decode(model, protected_read(path, root_only=root_only))


class RecoveryConfig(Model):
    config_version: Literal[1]
    coordinator_config_file: str
    control_deployment_id: ID
    current_control_manifest: Digest
    controller_signer_id: ID
    controller_private_file: str
    readiness: Endpoint
