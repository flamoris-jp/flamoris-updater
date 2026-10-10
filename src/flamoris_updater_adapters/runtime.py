from pathlib import Path
from types import SimpleNamespace

import httpx

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, dumps
from flamoris_updater.coordinator import Coordinator

from .artifacts import Fetcher, NativeStore
from .authority import Authority
from .backends import ApplicationBackend, LocalOwner, NativeDriver
from .config import Clock, CoordinatorConfig, HelperConfig, load, protected_read, signer
from .docker import DockerDriver, OCIStore
from .executor import HostExecutor
from .journal import Journal
from .releases import ReleaseStore
from .sources import ReleaseSources
from .transport import HTTPHost, UnixClient


def pinned_keys(configured):
    if len({k.id for k in configured}) != len(configured):
        raise UpdateError("invalid_profile", "Duplicate trusted key identity")
    return {k.id: k.key() for k in configured}


def releases(journal, keys, sources, clock):
    channels = {}
    for key in keys:
        if key.purpose == "catalog":
            for channel in key.channels:
                channels.setdefault(channel, []).append(key.id)
    store = ReleaseStore(journal, pinned_keys(keys), clock, channels)
    configured = [
        SimpleNamespace(
            application_id=s.application_id,
            channel=s.channel,
            catalog_url=s.catalog_url,
            catalog_signature_url=s.catalog_signature_url,
            origins=s.origins,
            tls_client=httpx.Client(
                verify=True, timeout=60, trust_env=False, follow_redirects=False
            ),
        )
        for s in sources
    ]
    sync = ReleaseSources(store, configured)
    store.refresh, store.ensure = sync.refresh, sync.ensure
    return store


def configuration_guard(path, root_only=False, files=()):
    expected = digest(protected_read(path, root_only=root_only))
    expected_files = {
        name: digest(protected_read(name, private=private)) for name, private in files
    }

    def guard():
        if digest(protected_read(path, root_only=root_only)) != expected or any(
            digest(protected_read(name, private=private)) != expected_files[name]
            for name, private in files
        ):
            raise UpdateError(
                "policy_changed",
                "Restart with the new protected configuration after reconciling active Jobs",
            )

    return guard


def credential_files(cfg):
    files = []

    def visit(obj):
        if isinstance(obj, dict):
            for name, value in obj.items():
                if (
                    name
                    in {
                        "cert_file",
                        "key_file",
                        "signer_private_file",
                        "environment_file",
                    }
                    and value
                ):
                    files.append(
                        (value, name in {"key_file", "signer_private_file", "environment_file"})
                    )
                elif isinstance(value, (dict, list)):
                    visit(value)
        elif isinstance(obj, list):
            for child in obj:
                visit(child)

    visit(cfg.model_dump())
    return list(set(files))


def coordinator(path):
    cfg = load(CoordinatorConfig, path)
    clock, journal = Clock(cfg.clock_healthy), Journal(Path(cfg.state_directory))
    authority = Authority(journal, clock)
    signing = signer(cfg.signer_id, cfg.signer_private_file)
    store = releases(journal, cfg.release_keys, cfg.release_sources, clock)
    hosts = {
        h.host_id: HTTPHost(
            h.host_id, cfg.domain_id, h.endpoint, signing, lambda: int(journal.meta("epoch"))
        )
        for h in cfg.hosts
    }
    c = Coordinator(
        cfg.domain_id,
        journal,
        {p.id: p for p in cfg.profiles},
        {r.id: r for r in cfg.resources},
        store,
        hosts,
        authority,
        signing,
        pinned_keys(cfg.receipt_keys),
        clock,
        cfg.policy_revision,
    )
    c.guard = configuration_guard(path, files=credential_files(cfg))
    return cfg, c, None


def executor(path, root_only=True):
    cfg = load(HelperConfig, path, root_only=root_only)
    clock, journal = Clock(cfg.clock_healthy), Journal(Path(cfg.state_directory))
    profiles = {p.id: p for p in cfg.profiles}
    if (
        len(profiles) != len(cfg.profiles)
        or len({b.deployment_id for b in cfg.bindings}) != len(cfg.bindings)
        or set(profiles) != {b.deployment_id for b in cfg.bindings}
        or any(p.host_id != cfg.host_id for p in cfg.profiles)
    ):
        raise UpdateError("invalid_profile")
    import platform

    hardware = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}.get(platform.machine())
    if hardware is None or any(p.platform != hardware for p in cfg.profiles):
        raise UpdateError("unsupported_platform")
    owners, drivers, physical = {}, {}, set()
    for binding in cfg.bindings:
        p = profiles[binding.deployment_id]
        if (
            binding.kind != p.artifact_kind
            or p.role == "recovery-controller"
            or digest(dumps(binding)) != p.binding_revision
        ):
            raise UpdateError("invalid_profile")
        identity = (
            binding.kind,
            str(Path(binding.unit_file).resolve())
            if binding.kind == "native"
            else binding.container_name,
        )
        pointer_identity = (
            ("pointer", str(Path(binding.active_pointer).absolute()))
            if binding.kind == "native"
            else ("docker-pointer", binding.container_name)
        )
        if pointer_identity in physical:
            raise UpdateError("invalid_profile", "Release-pointer aliases are forbidden")
        physical.add(pointer_identity)
        if identity in physical:
            raise UpdateError("invalid_profile", "Execution-authority aliases are forbidden")
        physical.add(identity)
        owners[p.id] = LocalOwner(
            UnixClient(
                binding.owner.socket_path,
                binding.owner.timeout_seconds,
                binding.owner.expected_uid,
            )
        )
        if binding.kind == "native":
            sources = [s for s in cfg.release_sources if s.application_id == p.application_id]
            if len(sources) != 1:
                raise UpdateError(
                    "invalid_profile", "Exactly one artifact-origin policy is required"
                )
            source = sources[0]
            client = httpx.Client(verify=True, timeout=60, trust_env=False, follow_redirects=False)
            store = NativeStore(
                Path(cfg.staging_directory),
                Fetcher(source.origins, client),
                cfg.quota.max_download_bytes,
                cfg.quota.max_expanded_bytes,
                cfg.quota.max_files,
                cfg.quota.reserve_bytes,
            )
            drivers[p.id] = NativeDriver(
                store,
                binding.unit,
                Path(binding.unit_file),
                binding.unit_digest,
                Path(binding.active_pointer),
            )
            drivers[p.id].control_state_directory = binding.control_state_directory
            drivers[p.id].python_executable = binding.python_executable
        else:
            fetcher = Fetcher(
                [binding.registry_origin],
                httpx.Client(
                    verify=True,
                    timeout=60,
                    trust_env=False,
                    follow_redirects=False,
                ),
            )
            drivers[p.id] = DockerDriver(OCIStore(fetcher, binding, cfg.quota), binding, journal)
    store = releases(journal, cfg.release_keys, cfg.release_sources, clock)
    signing = signer(cfg.host_id, cfg.signer_private_file)
    host = HostExecutor(
        cfg.host_id,
        cfg.domain_id,
        journal,
        profiles,
        store,
        ApplicationBackend(owners, drivers, signing),
        signing,
        pinned_keys(cfg.authorities),
        pinned_keys(cfg.receipt_keys),
        clock,
        resources={r.id: r for r in cfg.resources},
    )
    host.guard = configuration_guard(path, root_only=root_only, files=credential_files(cfg))
    return cfg, host
